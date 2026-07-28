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

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path


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
