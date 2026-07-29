# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the FTS5-backed keyword MemoryRecall."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.entities import SemanticFact

if TYPE_CHECKING:
    from pathlib import Path


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def populated(tmp_path: Path) -> SqliteMemoryRepo:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="bob loves jazz music"))
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="bob hates loud noise"))
    await repo.save_fact(SemanticFact(ts=_ts(), category="fact", content="the sky is blue today"))
    return repo


async def test_recall_finds_keyword_match(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("jazz", k=5)

    # Assert
    assert any("jazz" in str(r["content"]) for r in results)
    assert all("content" in r and "score" in r for r in results)
    await populated.close()


async def test_recall_carries_semantic_visibility(tmp_path: Path) -> None:
    # BOB-066 2.6: the recall item carries the fact's visibility provenance so the
    # application filter (may_surface) can withhold owner_private memory from a guest.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_fact(
        SemanticFact(
            ts=_ts(), category="pref", content="bob loves jazz", visibility="owner_private"
        )
    )
    recall = Fts5MemoryRecall(repo)

    results = await recall.recall("jazz", k=5)

    assert any(r.get("visibility") == "owner_private" for r in results)
    await repo.close()


async def test_recall_carries_episodic_visibility(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "vova: секрет владельца\nbob: ага",
            "visibility": "owner_private",
        }
    )
    recall = Fts5MemoryRecall(repo)

    results = await recall.recall("секрет", k=5)

    assert any(r.get("visibility") == "owner_private" for r in results)
    await repo.close()


async def test_legacy_row_recall_visibility_is_none_public(populated: SqliteMemoryRepo) -> None:
    # A fact saved without visibility (NULL) surfaces with visibility None (= public).
    recall = Fts5MemoryRecall(populated)

    results = await recall.recall("jazz", k=5)

    assert all(r.get("visibility") is None for r in results)
    await populated.close()


async def test_recall_respects_k_limit(populated: SqliteMemoryRepo) -> None:
    # Arrange: "bob" matches two facts.
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("bob", k=1)

    # Assert
    assert len(results) == 1
    await populated.close()


async def test_recall_returns_empty_on_no_match(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("zzzunmatchedzzz", k=5)

    # Assert
    assert results == []
    await populated.close()


async def test_recall_handles_special_fts_characters(populated: SqliteMemoryRepo) -> None:
    # Arrange: raw user text may contain FTS5 operator characters.
    recall = Fts5MemoryRecall(populated)

    # Act / Assert: must not raise an FTS5 syntax error.
    results = await recall.recall('jazz "(music)" OR', k=5)
    assert isinstance(results, list)
    await populated.close()


async def test_recall_empty_query_returns_empty(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act / Assert
    assert await recall.recall("   ", k=5) == []
    await populated.close()


async def test_recall_surfaces_old_episode_and_fact(tmp_path: Path) -> None:
    # Fix A: recall must search the whole conversation archive, not only
    # extracted facts. An old episodic turn that was never fact-extracted must
    # still surface by keyword, alongside any matching semantic fact.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    # An old un-extracted conversation turn (only in episodic_log).
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "user_message",
            "content": "my name is Vladimir and I love sailing",
        }
    )
    # A distilled fact mentioning the same keyword.
    await repo.save_fact(
        SemanticFact(ts=_ts(), category="identity", content="the user is named Vladimir")
    )
    recall = Fts5MemoryRecall(repo)

    results = await recall.recall("Vladimir", k=10)

    contents = [str(r["content"]) for r in results]
    # The old episode is reachable purely from the episodic archive.
    assert any("sailing" in c for c in contents)
    # The semantic fact still surfaces too.
    assert any("named Vladimir" in c for c in contents)
    await repo.close()


async def test_recall_backfills_preexisting_episodes(tmp_path: Path) -> None:
    # CRITICAL: a live db may already hold episodes written before the episodic
    # FTS index existed. Re-initialising must backfill them so they become
    # searchable — without re-applying the FTS triggers (idempotent).
    db_path = tmp_path / "bob.db"
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    content = "ancient turn about quantum entanglement"
    await repo.save_episode(
        {"ts": _ts().isoformat(), "event_type": "user_message", "content": content}
    )
    # Simulate a turn written before the episodic FTS existed: evict its index
    # entry (external-content FTS5 needs a 'delete' token, not plain DELETE).
    await repo.connection.execute(
        "INSERT INTO episodic_fts (episodic_fts, rowid, content) VALUES ('delete', 1, ?)",
        (content,),
    )
    await repo.connection.commit()
    # Pre-condition: the un-indexed turn is NOT yet searchable.
    pre = await Fts5MemoryRecall(repo).recall("entanglement", k=5)
    assert pre == []
    await repo.close()

    # A fresh init over the same file must rebuild the missing index entries.
    reopened = SqliteMemoryRepo(db_path)
    await reopened.initialize()
    recall = Fts5MemoryRecall(reopened)
    results = await recall.recall("entanglement", k=5)

    assert any("entanglement" in str(r["content"]) for r in results)
    await reopened.close()


async def test_recall_tags_result_sources(populated: SqliteMemoryRepo) -> None:
    # Each recalled item carries a source tag so callers can tell archive turns
    # from distilled facts.
    recall = Fts5MemoryRecall(populated)

    results = await recall.recall("jazz", k=5)

    assert all("source" in r for r in results)
    assert all(r["source"] in {"semantic", "episodic"} for r in results)
    await populated.close()


async def test_recall_survives_a_process_restart(tmp_path: Path) -> None:
    # PRD US-3: facts must be keyword-recallable after a process restart —
    # the FTS5 index lives on disk and is not lost when the process dies.
    db_path = tmp_path / "bob.db"

    # Arrange: a first "process" persists a fact, then closes (dies).
    first = SqliteMemoryRepo(db_path)
    await first.initialize()
    await first.save_fact(
        SemanticFact(ts=_ts(), category="personal", content="user adores deep-space probes")
    )
    await first.close()

    # Act: a brand-new repo + recall over the same file simulates a restart.
    second = SqliteMemoryRepo(db_path)
    await second.initialize()
    recall = Fts5MemoryRecall(second)
    results = await recall.recall("probes", k=5)

    # Assert: the fact survived and is still recallable by keyword.
    assert any("probes" in str(r["content"]) for r in results)
    await second.close()
