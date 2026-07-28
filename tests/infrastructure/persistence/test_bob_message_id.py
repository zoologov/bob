# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-050 .1 — bob_message_id linkage on episodic memory.

Covers the additive ``episodic_log.bob_message_id`` column + its index (fresh DB
and the idempotent migration of a pre-existing column-less DB), persisting the
outgoing Bob message_id on write, and the read seam ``episode_by_bob_message_id``
that links a reaction back to the episode (and Bob's reply text).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path


def _ts(day: int = 18, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=UTC)


def _episode(
    *, ts: datetime, content: str, bob_message_id: int | None
) -> dict[str, object]:
    return {
        "ts": ts.isoformat(),
        "event_type": "message",
        "content": content,
        "bob_message_id": bob_message_id,
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


async def test_fresh_db_has_bob_message_id_column_and_index(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    columns = await _column_names(tmp_path / "bob.db", "episodic_log")
    indexes = await _index_names(tmp_path / "bob.db", "episodic_log")
    assert "bob_message_id" in columns
    assert "idx_episodic_bob_message_id" in indexes


# --- Migration (pre-existing column-less DB) ----------------------------------


async def test_migration_adds_bob_message_id_idempotently(tmp_path: Path) -> None:
    # Arrange: a db created by an EARLIER schema with NO bob_message_id column.
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
    assert "bob_message_id" in columns
    assert "idx_episodic_bob_message_id" in indexes
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT bob_message_id FROM episodic_log WHERE content = 'legacy turn'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    assert row is not None
    assert row["bob_message_id"] is None


# --- Persist + read seam ------------------------------------------------------


async def test_save_episode_persists_bob_message_id(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_episode(
        _episode(ts=_ts(), content="Ada: hi\nbob: hey", bob_message_id=4242)
    )
    episode = await repo.episode_by_bob_message_id(4242)

    assert episode is not None
    assert episode["bob_message_id"] == 4242
    assert episode["content"] == "Ada: hi\nbob: hey"
    await repo.close()


async def test_episode_by_bob_message_id_returns_none_for_unknown(
    tmp_path: Path,
) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        _episode(ts=_ts(), content="Ada: hi\nbob: hey", bob_message_id=10)
    )

    # A reaction on a message Bob never sent → no episode → filter drops it.
    assert await repo.episode_by_bob_message_id(999) is None
    await repo.close()


async def test_episode_by_bob_message_id_returns_most_recent_match(
    tmp_path: Path,
) -> None:
    # Two episodes carry the same id (e.g. across restarts); newest wins.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        _episode(ts=_ts(hour=9), content="old reply", bob_message_id=7)
    )
    await repo.save_episode(
        _episode(ts=_ts(hour=11), content="new reply", bob_message_id=7)
    )

    episode = await repo.episode_by_bob_message_id(7)

    assert episode is not None
    assert episode["content"] == "new reply"
    await repo.close()


async def test_save_episode_without_bob_message_id_defaults_null(
    tmp_path: Path,
) -> None:
    # A turn where Bob sent no message (silent/tick) carries no link.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "Ada: hi\nbob: (silent)",
        }
    )

    assert await repo.episode_by_bob_message_id(1) is None
    await repo.close()
