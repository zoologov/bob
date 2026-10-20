# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the BOB-021 consolidation seam on SqliteMemoryRepo.

The migration (``episodic_log.consolidated``) is additive and idempotent, and the
three consolidation methods — selecting OLD un-consolidated non-digest episodes,
writing a digest episode (embedded on write), and flagging sources — keep the
archive non-destructive: originals are only marked, never removed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.kernel.interlocutor import Trust
from bob.kernel.visibility import VISIBILITY_OWNER_PRIVATE
from bob.memory.adapters.hybrid_recall import HybridMemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.work_journal import WORK_EVENT_TYPE
from bob.social.disclosure import filter_surfaceable, transfer_needs_consent
from tests.support.fake_embedder import FakeEmbedder

if TYPE_CHECKING:
    from pathlib import Path

    from bob.application.router.llm_router import LLMRequest


_DIM = 1024  # must match the schema's float[1024] (BGE-M3) or on-write embeds are dropped


def _ts(day: int = 18, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def _column_names(db_path: Path, table: str) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row[1]) for row in rows}


async def test_migration_adds_consolidated_column(tmp_path: Path) -> None:
    # Arrange / Act
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    # Assert: the additive column landed.
    columns = await _column_names(tmp_path / "bob.db", "episodic_log")
    assert "consolidated" in columns


async def test_migration_is_idempotent_on_an_existing_db(tmp_path: Path) -> None:
    # Arrange: a db created by an EARLIER schema with NO consolidated column.
    db_path = tmp_path / "bob.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        "CREATE TABLE episodic_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "event_type TEXT NOT NULL, content TEXT NOT NULL, "
        "mood_snapshot TEXT, tags TEXT NOT NULL DEFAULT '')"
    )
    await conn.execute(
        "INSERT INTO episodic_log (ts, event_type, content) VALUES (?, ?, ?)",
        (_ts().isoformat(), "message", "legacy turn"),
    )
    await conn.commit()
    await conn.close()

    # Act: initialise (runs the migration), twice, over the legacy db.
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.initialize()
    await repo.close()

    # Assert: column added; the pre-existing row defaults to consolidated=0.
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT consolidated FROM episodic_log WHERE content = 'legacy turn'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    assert row is not None
    assert row["consolidated"] == 0


async def test_select_consolidatable_returns_old_unconsolidated_non_digests(
    repo: SqliteMemoryRepo,
) -> None:
    # Arrange: an OLD message, a RECENT message, an OLD digest.
    await repo.save_episode(
        {"ts": _ts(day=1).isoformat(), "event_type": "message", "content": "old one"}
    )
    await repo.save_episode(
        {"ts": _ts(day=28).isoformat(), "event_type": "message", "content": "recent one"}
    )
    await repo.save_episode(
        {"ts": _ts(day=1).isoformat(), "event_type": "digest", "content": "old digest"}
    )
    cutoff = _ts(day=15)

    # Act
    rows = await repo.select_consolidatable_episodes(older_than=cutoff, limit=10)

    # Assert: only the old, un-consolidated, non-digest episode is eligible.
    assert [r["content"] for r in rows] == ["old one"]
    assert all("id" in r for r in rows)
    await repo.close()


async def test_select_consolidatable_honours_the_batch_limit(
    repo: SqliteMemoryRepo,
) -> None:
    # Arrange: three old eligible episodes.
    for n in range(3):
        await repo.save_episode(
            {"ts": _ts(day=1, hour=n).isoformat(), "event_type": "message", "content": f"e{n}"}
        )

    # Act
    rows = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=2)

    # Assert: capped at the batch size, oldest first.
    assert len(rows) == 2
    assert [r["content"] for r in rows] == ["e0", "e1"]
    await repo.close()


async def test_save_digest_writes_a_digest_episode(repo: SqliteMemoryRepo) -> None:
    # Act
    await repo.save_digest(
        {
            "ts": _ts().isoformat(),
            "content": "digest of three turns",
            "tags": "consolidation",
        }
    )

    # Assert: a digest episode exists and is recallable like any episode.
    episodes = await repo.load_episodes(limit=10)
    digests = [e for e in episodes if e["event_type"] == "digest"]
    assert len(digests) == 1
    assert digests[0]["content"] == "digest of three turns"
    await repo.close()


async def test_save_digest_is_not_itself_consolidatable(repo: SqliteMemoryRepo) -> None:
    # Arrange: a digest written in the past.
    await repo.save_digest(
        {"ts": _ts(day=1).isoformat(), "content": "an old digest", "tags": ""}
    )

    # Act
    rows = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=10)

    # Assert: digests are excluded from re-consolidation (idempotent guardrail).
    assert rows == []
    await repo.close()


async def test_mark_consolidated_is_non_destructive(repo: SqliteMemoryRepo) -> None:
    # Arrange: two old episodes.
    for n in range(2):
        await repo.save_episode(
            {"ts": _ts(day=1, hour=n).isoformat(), "event_type": "message", "content": f"m{n}"}
        )
    rows = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=10)
    ids = [int(str(r["id"])) for r in rows]

    # Act
    await repo.mark_consolidated(ids)

    # Assert: originals still present (non-destructive) but no longer eligible.
    episodes = await repo.load_episodes(limit=10)
    assert {e["content"] for e in episodes} == {"m0", "m1"}
    remaining = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=10)
    assert remaining == []
    await repo.close()


async def test_mark_consolidated_empty_is_a_noop(repo: SqliteMemoryRepo) -> None:
    # Act / Assert: marking nothing must not raise.
    await repo.mark_consolidated([])
    await repo.close()


async def test_select_consolidatable_excludes_the_work_journal(
    repo: SqliteMemoryRepo,
) -> None:
    # BOB-087.C8 (provenance laundering): a distilled ``work`` episode folded into a digest
    # would come back as an ordinary ``digest`` row — its work provenance gone, so the
    # register filter goes blind and Bob's dev war-stories leak into casual recall forever.
    # Already-distilled work memory is therefore never re-distilled.
    await repo.save_episode(
        {
            "ts": _ts(day=1).isoformat(),
            "event_type": WORK_EVENT_TYPE,
            "content": "я попросил GUPPI поднять лимит буфера, тесты позеленели",
            "tags": "work,dev,actor:bob",
        }
    )
    await repo.save_episode(
        {"ts": _ts(day=1).isoformat(), "event_type": "message", "content": "old chat"}
    )

    rows = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=10)

    assert [r["content"] for r in rows] == ["old chat"]
    await repo.close()


# --- Privacy label on the fold path (bob-g7t) ---------------------------------


async def test_select_consolidatable_carries_the_privacy_label(
    repo: SqliteMemoryRepo,
) -> None:
    """🔴 bob-g7t: the use-case can only inherit a label the SELECT actually hands it.

    Without ``visibility`` in the projection the fold step sees ``None`` for every
    source and stamps every digest «public» — green on fakes, leaking in production
    (§0.3 п.4).
    """
    # Arrange: an old private episode.
    await repo.save_episode(
        {
            "ts": _ts(day=1).isoformat(),
            "event_type": "message",
            "content": "личное",
            "visibility": "owner_private",
        }
    )

    # Act
    rows = await repo.select_consolidatable_episodes(older_than=_ts(day=15), limit=10)

    # Assert: the label rides along with the source.
    assert [r["visibility"] for r in rows] == ["owner_private"]
    await repo.close()


async def test_save_digest_persists_the_privacy_label(repo: SqliteMemoryRepo) -> None:
    # Act
    await repo.save_digest(
        {
            "ts": _ts().isoformat(),
            "content": "сводка приватного окна",
            "tags": "consolidation",
            "mood_snapshot": f"{_ts(day=1).isoformat()}..{_ts(day=2).isoformat()}",
            "visibility": "owner_private",
        }
    )

    # Assert: the digest row is stored private, not NULL (= public).
    assert await _digest_visibilities(repo) == ["owner_private"]
    await repo.close()


async def test_a_folded_private_episode_stays_private_for_a_guest(
    tmp_path: Path,
) -> None:
    """End-to-end через настоящий SQLite: свёртка не отмывает приватность.

    Наблюдаемое поведение через границу — что видит ГОСТЬ и что говорит гейт переноса,
    — а не внутреннее состояние. Роутер фейковый (Tier-0 локальный), хранилище настоящее.
    """
    # Arrange: a real repo holding one OLD owner-private episode.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts(day=1).isoformat(),
            "event_type": "message",
            "content": "я лечу спину, никому не говори",
            "visibility": VISIBILITY_OWNER_PRIVATE,
        }
    )

    # Act: fold it exactly as the reflect tick would.
    await ConsolidateMemory(
        store=repo,
        router=_StubRouter("сводка: он лечит спину"),
        clock=_FixedClock(_ts(day=28)),
    ).run()

    # Assert: the digest exists, a GUEST is not told it, and carrying it to a public
    # chat asks the owner first (BOB-090.B gate reads the same label).
    digest = await _digest_row(repo)
    assert digest is not None
    assert filter_surfaceable([digest], Trust.GUEST) == ()
    assert transfer_needs_consent([digest], destination_public=True)
    # …while the owner himself still sees his own memory (INV-7).
    assert filter_surfaceable([digest], Trust.TRUSTED) == (digest,)
    await repo.close()


async def test_legacy_digests_are_repaired_from_their_provenance(
    tmp_path: Path,
) -> None:
    """🔴 bob-g7t: дайджесты, записанные ДО фикса, дозаполняются по источникам.

    Живая база несла 21 такой дайджест без метки. Метку считаем по провенансу
    (ts-диапазон источников), а не «всем приватное» и не «оставить как есть»: это данные
    owner'а, и честный ответ даёт сама база.
    """
    # Arrange: two pre-fix digests — one whose window held a private source, one whose
    # window was entirely public — both stored with NO label, as the old code wrote them.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await _fold_window(repo, day=1, visibility=VISIBILITY_OWNER_PRIVATE)
    await _fold_window(repo, day=3, visibility="public")
    await _strip_digest_labels(repo)
    await repo.close()

    # Act: Bob boots again — the repair runs as part of the migration chain.
    repaired = SqliteMemoryRepo(tmp_path / "bob.db")
    await repaired.initialize()

    # Assert: the digest of the private window became private; the public one stayed
    # public (no blanket over-labelling — public memory must keep surfacing).
    assert await _digest_visibilities(repaired) == [VISIBILITY_OWNER_PRIVATE, "public"]
    await repaired.close()


async def test_a_digest_whose_sources_cannot_be_found_is_repaired_conservatively(
    tmp_path: Path,
) -> None:
    """Провенанс не разрешился → строгая метка (INV-8: сомнение придерживает)."""
    # Arrange: a digest whose ts-range matches no consolidated source at all.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_digest(
        {
            "ts": _ts(day=2).isoformat(),
            "content": "дайджест без прослеживаемых источников",
            "tags": "consolidation",
            "mood_snapshot": "не-провенанс",
        }
    )
    await _strip_digest_labels(repo)
    await repo.close()

    # Act
    repaired = SqliteMemoryRepo(tmp_path / "bob.db")
    await repaired.initialize()

    # Assert
    assert await _digest_visibilities(repaired) == [VISIBILITY_OWNER_PRIVATE]
    await repaired.close()


async def test_the_repair_leaves_an_already_labelled_digest_alone(
    tmp_path: Path,
) -> None:
    """Идемпотентно: починка трогает только строки БЕЗ метки, второй запуск — no-op."""
    # Arrange: a digest of a private window, written by the FIXED code (already labelled),
    # plus a public source in the same window that would flip nothing.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await _fold_window(repo, day=1, visibility="public")
    await _set_digest_label(repo, VISIBILITY_OWNER_PRIVATE)
    await repo.close()

    # Act: two more boots.
    for _ in range(2):
        booted = SqliteMemoryRepo(tmp_path / "bob.db")
        await booted.initialize()
        await booted.close()

    # Assert: the stored label survived — the repair never RE-decides a labelled row.
    final = SqliteMemoryRepo(tmp_path / "bob.db")
    await final.initialize()
    assert await _digest_visibilities(final) == [VISIBILITY_OWNER_PRIVATE]
    await final.close()


async def test_a_folded_private_digest_stays_withheld_through_real_recall(
    tmp_path: Path,
) -> None:
    """🔴 bob-g7t, соседний путь: дайджест приезжает гостю ЧЕРЕЗ НАСТОЯЩУЮ ДВЕРЬ recall.

    Прямое чтение строки доказало бы только запись. Здесь дайджест поднимается тем же
    гибридным recall'ом, каким его поднял бы живой ход (включая ``surface_old`` — а
    «старое релевантное» это как раз дайджесты), и уже поднятый прогоняется через фильтр
    разглашения. Так проверяется, что метка не теряется по дороге ни в одной из дверей.
    """
    # Arrange: a real store with a deterministic embedder, one OLD private episode.
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=FakeEmbedder(dim=_DIM))
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts(day=1).isoformat(),
            "event_type": "message",
            "content": "секретный план переезда",
            "visibility": VISIBILITY_OWNER_PRIVATE,
        }
    )
    await ConsolidateMemory(
        store=repo,
        router=_StubRouter("секретный план переезда обсуждали"),
        clock=_FixedClock(_ts(day=28)),
    ).run()
    recall = HybridMemoryRecall(repo, FakeEmbedder(dim=_DIM))

    # Act: recall the way a live turn does — plain, and with the old-memory blend.
    plain = await recall.recall("секретный план переезда", k=5)
    with_old = await recall.recall("секретный план переезда", k=5, surface_old=True)

    # Assert: the digest is among the hits, and every door hands the guest nothing.
    await repo.close()
    assert any("обсуждали" in str(hit["content"]) for hit in plain)
    assert filter_surfaceable(plain, Trust.GUEST) == ()
    assert filter_surfaceable(with_old, Trust.GUEST) == ()


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _StubRouter:
    """Tier-0 stand-in: replies with a scripted digest line, never touches the network."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def run(self, request: LLMRequest) -> str:
        del request
        return self._reply


async def _fold_window(
    repo: SqliteMemoryRepo, *, day: int, visibility: str | None
) -> None:
    """Write one episode of ``visibility`` and fold it into a digest, as the tick would."""
    await repo.save_episode(
        {
            "ts": _ts(day=day).isoformat(),
            "event_type": "message",
            "content": f"эпизод дня {day}",
            "visibility": visibility,
        }
    )
    await ConsolidateMemory(
        store=repo,
        router=_StubRouter(f"сводка дня {day}"),
        clock=_FixedClock(_ts(day=day + 20)),
    ).run()


async def _digest_row(repo: SqliteMemoryRepo) -> dict[str, object] | None:
    """The single digest row as recall would see it (content + its privacy label)."""
    rows = await _query(
        repo, "SELECT content, visibility FROM episodic_log WHERE event_type = 'digest'"
    )
    return None if not rows else {"content": rows[0][0], "visibility": rows[0][1]}


async def _digest_visibilities(repo: SqliteMemoryRepo) -> list[str | None]:
    """The stored privacy label of every digest, oldest first (``None`` = no label)."""
    rows = await _query(
        repo,
        "SELECT visibility FROM episodic_log WHERE event_type = 'digest' ORDER BY id",
    )
    return [row[0] if isinstance(row[0], str) else None for row in rows]


async def _strip_digest_labels(repo: SqliteMemoryRepo) -> None:
    """Reproduce the PRE-fix on-disk state: a digest row with no visibility at all."""
    await _execute(repo, "UPDATE episodic_log SET visibility = NULL WHERE event_type = 'digest'")


async def _set_digest_label(repo: SqliteMemoryRepo, visibility: str) -> None:
    await _execute(
        repo,
        "UPDATE episodic_log SET visibility = ? WHERE event_type = 'digest'",
        (visibility,),
    )


async def _query(repo: SqliteMemoryRepo, sql: str) -> list[tuple[object, ...]]:
    """Read raw rows through the repo's own connection seam (a persistence-level test)."""
    async with repo.connection.execute(sql) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


async def _execute(
    repo: SqliteMemoryRepo, sql: str, params: tuple[object, ...] = ()
) -> None:
    """Arrange raw rows — used to reproduce the PRE-fix on-disk state."""
    await repo.connection.execute(sql, params)
    await repo.connection.commit()
