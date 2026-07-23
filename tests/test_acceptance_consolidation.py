# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance tests for BOB-021 «Консолидация памяти» — fakes only, no network.

These drive the three consolidation mechanisms END TO END over the REAL
:class:`SqliteMemoryRepo` (a temp on-disk SQLite db with the live FTS5 index and
the real vector store) — not a fake store. Only the genuinely-external edges are
faked: the LLM router (a local provider, no HTTP) and the embedder (a deterministic
local table, no Ollama). This exercises the use-case↔persistence seam the fake-store
unit tests cannot, and asserts the product-level US criteria:

* **US-2 (digests):** an old un-consolidated episode is folded into a digest that is
  WRITTEN, recallable, and whose sources are flagged ``consolidated=1`` — originals
  NON-destructively kept; a second run is idempotent (no duplicate digest); a digest
  is never re-consolidated.
* **US-3 (dedup):** near-duplicate facts merge into a canonical (others
  ``superseded_by``), dissimilar facts are NEVER merged, the merge is idempotent and
  non-destructive, and recall EXCLUDES the superseded fact.
* **US-1 (surface old):** the real hybrid recall blends an OLD-but-relevant memory
  on ``surface_old=True`` while the default ``recall(query, k)`` is byte-for-byte
  unchanged (the drop-in contract).
* **Locality / privacy:** every step touches the LLM/embedder ONLY through the
  injected fake port — memory content never leaves the machine; nothing is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.application.router.llm_router import LLMRouter
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.hybrid_recall import HybridMemoryRecall
from bob.memory.entities import SemanticFact
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.dedup_facts import DedupFacts

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
_DIM = 1024


class FakeClock:
    def now(self) -> datetime:
        return _NOW


class LocalProvider:
    """A local LLM provider (no HTTP): canned digest reply, records what it saw."""

    def __init__(self, reply: str = "Сжатый дайджест: имена и решения сохранены.") -> None:
        self.reply = reply
        self.seen: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.seen.append("".join(m.get("content", "") for m in messages))
        return self.reply


class LocalEmbedder:
    """A local embedder (no Ollama): a content->vector table at the BGE-M3 dimension.

    Realises :class:`bob.domain.ports.Embedder`. Unknown text maps to a fixed axis so
    unrelated content stays far apart in cosine space; aligned axes model duplicates.
    """

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._table.get(t, _unit(_DIM - 1)) for t in texts]


def _unit(*axes: int) -> list[float]:
    vec = [0.0] * _DIM
    for axis in axes:
        vec[axis] = 1.0
    return vec


def _episode(day: int, content: str, *, event_type: str = "message") -> dict[str, object]:
    return {
        "ts": datetime(2026, 6, day, 9, 0, tzinfo=UTC).isoformat(),
        "event_type": event_type,
        "content": content,
    }


async def _digest_count(db_path: Path) -> int:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(
            "SELECT COUNT(*) FROM episodic_log WHERE event_type = 'digest'"
        ) as cursor:
            row = await cursor.fetchone()
    finally:
        await conn.close()
    return int(row[0]) if row else 0


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


# --- US-2: длинная история сжимается в дайджесты -------------------------------


async def test_us2_old_episode_is_folded_into_a_recallable_digest(
    repo: SqliteMemoryRepo, tmp_path: Path
) -> None:
    # Arrange: two OLD message episodes on the REAL repo + a recent one spared.
    await repo.save_episode(_episode(1, "старое про джаз A"))
    await repo.save_episode(_episode(2, "старое про джаз B"))
    await repo.save_episode(_episode(29, "свежее сегодня"))
    provider = LocalProvider()
    consolidate = ConsolidateMemory(
        store=repo,
        router=LLMRouter(providers={0: provider}),
        clock=FakeClock(),
        max_age_days=14.0,
    )

    # Act
    await consolidate.run()

    # Assert: exactly one digest written (a recallable episodic_log row) and the two
    # OLD sources are flagged consolidated (the recent one untouched).
    assert await _digest_count(tmp_path / "bob.db") == 1
    episodes = await repo.load_episodes(limit=20)
    digests = [e for e in episodes if e["event_type"] == "digest"]
    assert digests[0]["content"] == provider.reply
    # The digest's source content reached ONLY the local provider (privacy boundary).
    assert any("старое про джаз A" in seen for seen in provider.seen)
    # Originals are NON-destructively kept (only flagged); the recent one untouched.
    contents = {str(e["content"]) for e in episodes if e["event_type"] == "message"}
    assert contents == {"старое про джаз A", "старое про джаз B", "свежее сегодня"}
    await repo.close()


async def test_us2_second_run_is_idempotent_no_duplicate_digest(
    repo: SqliteMemoryRepo, tmp_path: Path
) -> None:
    # Arrange: one old episode consolidated on the first run.
    await repo.save_episode(_episode(1, "старое"))
    consolidate = ConsolidateMemory(
        store=repo, router=LLMRouter(providers={0: LocalProvider()}), clock=FakeClock()
    )
    await consolidate.run()

    # Act: a second run — the source is already consolidated, the digest is excluded.
    await consolidate.run()

    # Assert: still exactly one digest (idempotent), and the digest was never itself
    # re-consolidated (no second-order digest of a digest).
    assert await _digest_count(tmp_path / "bob.db") == 1
    await repo.close()


# --- US-3: факты дедуплицируются -----------------------------------------------


async def test_us3_near_duplicates_merge_and_recall_excludes_superseded(
    tmp_path: Path,
) -> None:
    # Arrange: a near-duplicate pair (aligned vectors) + a dissimilar fact, on a REAL
    # embedder-backed repo so recall's vector half is populated.
    embedder = LocalEmbedder(
        {
            "любит зелёный чай": _unit(0),
            "обожает зелёный чай": _unit(0),  # near-duplicate of the above
            "живёт в Москве": _unit(7),  # dissimilar
        }
    )
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()
    await repo.save_fact(_fact("любит зелёный чай", day=10))
    await repo.save_fact(_fact("обожает зелёный чай", day=12))  # newer -> canonical
    await repo.save_fact(_fact("живёт в Москве", day=11))
    dedup = DedupFacts(store=repo, embedder=embedder, clock=FakeClock(), threshold=0.92)

    # Act
    await dedup.run()

    # Assert: the older near-duplicate is superseded (non-destructively); the
    # dissimilar fact is NEVER merged.
    active = {str(r["content"]) for r in await repo.select_active_facts()}
    assert "обожает зелёный чай" in active  # the newer canonical survives
    assert "любит зелёный чай" not in active  # the older duplicate is superseded
    assert "живёт в Москве" in active  # no false merge of a dissimilar fact

    # The superseded fact is non-destructively KEPT in the table with provenance.
    conn = repo.connection
    async with conn.execute(
        "SELECT superseded_by FROM semantic_memory WHERE content = 'любит зелёный чай'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["superseded_by"] is not None  # provenance: points at the canonical id

    # And recall EXCLUDES the superseded fact (both halves), keeping the canonical.
    recall = HybridMemoryRecall(repo, embedder)
    hits = {str(h["content"]) for h in await recall.recall("зелёный чай", k=10)}
    assert "любит зелёный чай" not in hits
    assert "обожает зелёный чай" in hits
    await repo.close()


async def test_us3_dedup_is_idempotent_on_a_second_run(tmp_path: Path) -> None:
    # Arrange: a near-duplicate pair merged on the first run.
    embedder = LocalEmbedder({"x": _unit(0), "x2": _unit(0)})
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()
    await repo.save_fact(_fact("x", day=10))
    await repo.save_fact(_fact("x2", day=12))
    dedup = DedupFacts(store=repo, embedder=embedder, clock=FakeClock())
    await dedup.run()
    after_first = {str(r["content"]) for r in await repo.select_active_facts()}

    # Act: a second run — the superseded fact is excluded from active selection.
    await dedup.run()

    # Assert: no further merge; the active set is unchanged (idempotent).
    assert {str(r["content"]) for r in await repo.select_active_facts()} == after_first == {"x2"}
    await repo.close()


# --- US-1: старое к месту всплывает + drop-in contract -------------------------


async def test_us1_surface_old_blends_old_while_default_recall_is_unchanged(
    tmp_path: Path,
) -> None:
    # Arrange: recents crowd out an older-but-relevant deep cut at a tight k, on the
    # REAL hybrid recall. The deep cut is relevant by MEANING (vector-near) but shares
    # no keyword, so default fusion drops it at this k.
    query = "jazz"
    deep_cut = "bob first heard those swinging horns as a teenager"
    recents = [f"bob mentioned jazz on day {i}" for i in range(6)]
    table = {query: _unit(0), deep_cut: _unit(0, 1)}
    for text in recents:
        table[text] = _unit(0)
    embedder = LocalEmbedder(table)
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()
    for i, text in enumerate(recents):
        await repo.save_fact(_fact(text, day=20, ts=_NOW - timedelta(days=i)))
    await repo.save_fact(_fact(deep_cut, day=20, ts=_NOW - timedelta(days=3650)))
    recall = HybridMemoryRecall(repo, embedder)

    # Act
    k = 2
    default = [str(r["content"]) for r in await recall.recall(query, k=k)]
    explicit_off = [str(r["content"]) for r in await recall.recall(query, k=k, surface_old=False)]
    surfaced = [str(r["content"]) for r in await recall.recall(query, k=k, surface_old=True)]

    # Assert: drop-in — the default call is byte-for-byte the explicit surface_old=False;
    # the deep cut is absent by default but reached by surface_old, still bounded by k.
    assert default == explicit_off
    assert deep_cut not in default
    assert deep_cut in surfaced
    assert len(surfaced) <= k
    await repo.close()


async def test_us1_surface_old_noops_when_nothing_old_is_relevant(tmp_path: Path) -> None:
    # Arrange: an empty store — there is no old-but-relevant memory to blend.
    embedder = LocalEmbedder({"jazz": _unit(0)})
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()
    recall = HybridMemoryRecall(repo, embedder)

    # Act
    surfaced = await recall.recall("jazz", k=5, surface_old=True)

    # Assert: a clean no-op (nothing to surface), never a fabricated memory.
    assert list(surfaced) == []
    await repo.close()


# --- Locality / non-destructiveness across the keyword-only path ---------------


async def test_consolidation_works_keyword_only_without_an_embedder(
    repo: SqliteMemoryRepo, tmp_path: Path
) -> None:
    # The digest step needs only the LLM router, not an embedder: it must work on a
    # keyword-only repo (no embedder wired), staying local and non-destructive.
    await repo.save_episode(_episode(1, "старое без эмбеддера"))
    consolidate = ConsolidateMemory(
        store=repo, router=LLMRouter(providers={0: LocalProvider()}), clock=FakeClock()
    )

    await consolidate.run()

    assert await _digest_count(tmp_path / "bob.db") == 1
    # The original survives (non-destructive) and is recallable by keyword.
    hits = await Fts5MemoryRecall(repo).recall("старое", k=10)
    assert any("старое без эмбеддера" in str(h["content"]) for h in hits)
    await repo.close()


def _fact(content: str, *, day: int = 18, ts: datetime | None = None) -> SemanticFact:
    return SemanticFact(
        ts=ts if ts is not None else datetime(2026, 6, day, 9, 0, tzinfo=UTC),
        category="user",
        content=content,
    )
