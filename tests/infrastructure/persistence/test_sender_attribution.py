# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-045 .1 — sender_id attribution on episodic memory.

Covers the additive ``episodic_log.sender_id`` column + its index (fresh DB and
the idempotent migration of a pre-existing column-less DB), persisting the
sender on write, the per-person read seam ``recent_episodes_for``, the
``sender_id`` carried by the recalled projection, and the best-effort,
idempotent backfill that maps a leading ``"<name>: "`` content prefix to a known
sender id (owner name -> owner_id; allowlisted names -> their ids).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from bob.domain.memory.entities import SemanticFact
from bob.infrastructure.persistence.fts_recall import Fts5MemoryRecall
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path


def _ts(day: int = 18, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=UTC)


def _episode(
    *, ts: datetime, content: str, sender_id: int | None
) -> dict[str, object]:
    return {
        "ts": ts.isoformat(),
        "event_type": "message",
        "content": content,
        "sender_id": sender_id,
    }


async def _column_names(db_path: Path, table: str) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row[1]) for row in rows}


async def _index_names(db_path: Path, table: str) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(f"PRAGMA index_list({table})") as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row[1]) for row in rows}


# --- Schema (fresh DB) --------------------------------------------------------


async def test_fresh_db_has_sender_id_column_and_index(tmp_path: Path) -> None:
    # Arrange / Act: a fresh DB built from schema.sql.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    # Assert: the additive column + its (sender_id, ts) index landed.
    columns = await _column_names(tmp_path / "bob.db", "episodic_log")
    indexes = await _index_names(tmp_path / "bob.db", "episodic_log")
    assert "sender_id" in columns
    assert "idx_episodic_sender" in indexes


# --- Migration (pre-existing column-less DB) ----------------------------------


async def test_migration_adds_sender_id_idempotently(tmp_path: Path) -> None:
    # Arrange: a db created by an EARLIER schema with NO sender_id column.
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

    # Act: initialise (runs the migration) TWICE over the legacy db.
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.initialize()
    await repo.close()

    # Assert: column + index added; the pre-existing row defaults to NULL.
    columns = await _column_names(db_path, "episodic_log")
    indexes = await _index_names(db_path, "episodic_log")
    assert "sender_id" in columns
    assert "idx_episodic_sender" in indexes
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT sender_id FROM episodic_log WHERE content = 'legacy turn'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    assert row is not None
    assert row["sender_id"] is None


# --- Persist + read seam ------------------------------------------------------


async def test_save_episode_persists_sender_id(tmp_path: Path) -> None:
    # Arrange
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    # Act
    await repo.save_episode(_episode(ts=_ts(), content="Ada: hi\nbob: hey", sender_id=7))
    rows = await repo.recent_episodes_for(7, 5)

    # Assert
    assert len(rows) == 1
    assert rows[0]["sender_id"] == 7
    assert rows[0]["content"] == "Ada: hi\nbob: hey"
    await repo.close()


async def test_recent_episodes_for_filters_newest_k_chronological(
    tmp_path: Path,
) -> None:
    # Arrange: interleaved turns from two senders.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(_episode(ts=_ts(hour=9), content="A1", sender_id=1))
    await repo.save_episode(_episode(ts=_ts(hour=10), content="B1", sender_id=2))
    await repo.save_episode(_episode(ts=_ts(hour=11), content="A2", sender_id=1))
    await repo.save_episode(_episode(ts=_ts(hour=12), content="A3", sender_id=1))

    # Act: last 2 episodes for sender 1.
    rows = await repo.recent_episodes_for(1, 2)

    # Assert: only sender 1, newest two, in chronological order.
    contents = [str(r["content"]) for r in rows]
    assert contents == ["A2", "A3"]
    assert all(r["sender_id"] == 1 for r in rows)
    await repo.close()


async def test_recent_episodes_for_nonpositive_k_is_empty(tmp_path: Path) -> None:
    # Arrange
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(_episode(ts=_ts(), content="A1", sender_id=1))

    # Act / Assert
    assert await repo.recent_episodes_for(1, 0) == []
    assert await repo.recent_episodes_for(1, -3) == []
    await repo.close()


# --- Recalled projection carries sender_id ------------------------------------


async def test_recalled_projection_carries_sender_id(tmp_path: Path) -> None:
    # Arrange: one episodic turn (with a sender) and one semantic fact (no sender).
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        _episode(ts=_ts(), content="Ada: tell me about jazz\nbob: sure", sender_id=42)
    )
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="bob loves jazz"))
    recall = Fts5MemoryRecall(repo)

    # Act
    results = await recall.recall("jazz", k=5)

    # Assert: the episodic hit carries its sender_id; the fact's stays None.
    by_source = {str(r["source"]): r for r in results}
    assert by_source["episodic"]["sender_id"] == 42
    assert by_source["semantic"]["sender_id"] is None
    await repo.close()


# --- Best-effort backfill -----------------------------------------------------


async def test_backfill_maps_owner_prefix_and_leaves_unknown_null(
    tmp_path: Path,
) -> None:
    # Arrange: a legacy db with NULL-sender rows whose content carries a name prefix.
    db_path = tmp_path / "bob.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        "CREATE TABLE episodic_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "event_type TEXT NOT NULL, content TEXT NOT NULL, "
        "mood_snapshot TEXT, tags TEXT NOT NULL DEFAULT '')"
    )
    await conn.executemany(
        "INSERT INTO episodic_log (ts, event_type, content) VALUES (?, 'message', ?)",
        [
            (_ts(hour=9).isoformat(), "Vova: привет\nbob: hi"),
            (_ts(hour=10).isoformat(), "Stranger: yo\nbob: hello"),
            (_ts(hour=11).isoformat(), "no prefix here"),
        ],
    )
    await conn.commit()
    await conn.close()

    # Act: initialise with an owner-name -> owner_id map; run init twice (idempotent).
    repo = SqliteMemoryRepo(db_path, name_to_sender_id={"Vova": 555})
    await repo.initialize()
    await repo.initialize()

    # Assert: owner row got the id; unknown name + no-prefix rows stay NULL.
    owner_rows = await repo.recent_episodes_for(555, 10)
    assert [str(r["content"]) for r in owner_rows] == ["Vova: привет\nbob: hi"]
    nulls = await _null_sender_contents(db_path)
    assert nulls == {"Stranger: yo\nbob: hello", "no prefix here"}
    await repo.close()


async def _null_sender_contents(db_path: Path) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        async with conn.execute(
            "SELECT content FROM episodic_log WHERE sender_id IS NULL"
        ) as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row["content"]) for row in rows}
