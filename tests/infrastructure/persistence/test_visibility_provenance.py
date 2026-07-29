# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-066 2.6 — visibility (scope-provenance) columns on memory.

Covers the additive ``episodic_log.visibility`` and ``semantic_memory.visibility``
columns (fresh DB + the idempotent migration of a pre-existing column-less DB), that
they persist on write, and — crucially — that a LEGACY row (written before the column
existed) reads back as ``NULL`` (which :func:`~bob.social.disclosure.may_surface` treats
as public, so BOB-051 unified memory stays intact and owner recall is byte-identical).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.entities import SemanticFact

if TYPE_CHECKING:
    from pathlib import Path


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


async def _column_names(db_path: Path, table: str) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row[1]) for row in rows}


# --- Schema (fresh DB) --------------------------------------------------------


async def test_fresh_db_has_visibility_columns(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    assert "visibility" in await _column_names(tmp_path / "bob.db", "episodic_log")
    assert "visibility" in await _column_names(tmp_path / "bob.db", "semantic_memory")


# --- Migration (pre-existing column-less DB) ----------------------------------


async def test_migration_adds_visibility_idempotently(tmp_path: Path) -> None:
    # Arrange: a db created by an EARLIER schema with NO visibility columns.
    db_path = tmp_path / "bob.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        "CREATE TABLE episodic_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "event_type TEXT NOT NULL, content TEXT NOT NULL, "
        "mood_snapshot TEXT, tags TEXT NOT NULL DEFAULT '')"
    )
    await conn.execute(
        "CREATE TABLE semantic_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "category TEXT NOT NULL, content TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0)"
    )
    await conn.execute(
        "INSERT INTO episodic_log (ts, event_type, content) VALUES (?, ?, ?)",
        (_ts().isoformat(), "message", "legacy turn"),
    )
    await conn.execute(
        "INSERT INTO semantic_memory (ts, category, content) VALUES (?, ?, ?)",
        (_ts().isoformat(), "pref", "legacy fact"),
    )
    await conn.commit()
    await conn.close()

    # Act: initialise (runs the migration) TWICE over the legacy db (idempotent).
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.initialize()
    await repo.close()

    # Assert: columns added; the pre-existing rows read back NULL (= public).
    assert "visibility" in await _column_names(db_path, "episodic_log")
    assert "visibility" in await _column_names(db_path, "semantic_memory")
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT visibility FROM episodic_log WHERE content = 'legacy turn'"
    ) as cursor:
        episodic_row = await cursor.fetchone()
    async with conn.execute(
        "SELECT visibility FROM semantic_memory WHERE content = 'legacy fact'"
    ) as cursor:
        semantic_row = await cursor.fetchone()
    await conn.close()
    assert episodic_row is not None
    assert episodic_row["visibility"] is None
    assert semantic_row is not None
    assert semantic_row["visibility"] is None


# --- Persist ------------------------------------------------------------------


async def test_save_episode_persists_visibility(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "vova: секрет\nbob: ага",
            "visibility": "owner_private",
        }
    )
    conn = await aiosqlite.connect(tmp_path / "bob.db")
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT visibility FROM episodic_log WHERE content LIKE 'vova:%'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    await repo.close()
    assert row is not None
    assert row["visibility"] == "owner_private"


async def test_save_fact_persists_visibility(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_fact(
        SemanticFact(
            ts=_ts(), category="pref", content="секретный факт", visibility="owner_private"
        )
    )
    conn = await aiosqlite.connect(tmp_path / "bob.db")
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT visibility FROM semantic_memory WHERE content = 'секретный факт'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    await repo.close()
    assert row is not None
    assert row["visibility"] == "owner_private"
