# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the BOB-021 fact-dedup seam on SqliteMemoryRepo.

The migration (``semantic_memory.superseded_by``) is additive and idempotent. The
dedup methods — selecting ACTIVE (un-superseded) facts and flagging duplicates as
superseded into a canonical fact — keep the archive non-destructive: a merged fact
is only marked, never removed, with provenance (the canonical's id) preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.entities import SemanticFact

if TYPE_CHECKING:
    from pathlib import Path


def _ts(day: int = 18, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=UTC)


def _fact(content: str, *, day: int = 18, category: str = "user") -> SemanticFact:
    return SemanticFact(ts=_ts(day=day), category=category, content=content)


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


async def test_migration_adds_superseded_by_column(tmp_path: Path) -> None:
    # Arrange / Act
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    # Assert: the additive column landed.
    columns = await _column_names(tmp_path / "bob.db", "semantic_memory")
    assert "superseded_by" in columns


async def test_migration_is_idempotent_on_an_existing_db(tmp_path: Path) -> None:
    # Arrange: a db created by an EARLIER schema with NO superseded_by column.
    db_path = tmp_path / "bob.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        "CREATE TABLE semantic_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "category TEXT NOT NULL, content TEXT NOT NULL, "
        "confidence REAL NOT NULL DEFAULT 1.0)"
    )
    await conn.execute(
        "INSERT INTO semantic_memory (ts, category, content) VALUES (?, ?, ?)",
        (_ts().isoformat(), "user", "legacy fact"),
    )
    await conn.commit()
    await conn.close()

    # Act: initialise (runs the migration), twice, over the legacy db.
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.initialize()
    await repo.close()

    # Assert: column added; the pre-existing row defaults to superseded_by = NULL.
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT superseded_by FROM semantic_memory WHERE content = 'legacy fact'"
    ) as cursor:
        row = await cursor.fetchone()
    await conn.close()
    assert row is not None
    assert row["superseded_by"] is None


async def test_select_active_facts_returns_only_unsuperseded(repo: SqliteMemoryRepo) -> None:
    # Arrange: two facts; one superseded into the other.
    await repo.save_fact(_fact("canonical fact"))
    await repo.save_fact(_fact("duplicate fact"))
    rows = await repo.select_active_facts()
    ids = {str(r["content"]): int(str(r["id"])) for r in rows}
    await repo.supersede_facts({ids["duplicate fact"]: ids["canonical fact"]})

    # Act
    active = await repo.select_active_facts()

    # Assert: only the canonical (un-superseded) fact is active.
    assert [r["content"] for r in active] == ["canonical fact"]
    await repo.close()


async def test_select_active_facts_carries_id_ts_content(repo: SqliteMemoryRepo) -> None:
    # Arrange
    await repo.save_fact(_fact("a durable fact", day=3))

    # Act
    rows = await repo.select_active_facts()

    # Assert: each row carries the fields dedup needs.
    assert len(rows) == 1
    row = rows[0]
    assert set(row) >= {"id", "ts", "content"}
    assert row["content"] == "a durable fact"
    await repo.close()


async def test_supersede_facts_is_non_destructive(repo: SqliteMemoryRepo) -> None:
    # Arrange: two facts.
    await repo.save_fact(_fact("keep me"))
    await repo.save_fact(_fact("merge me"))
    rows = await repo.select_active_facts()
    ids = {str(r["content"]): int(str(r["id"])) for r in rows}

    # Act
    await repo.supersede_facts({ids["merge me"]: ids["keep me"]})

    # Assert: the superseded row still exists with provenance (the canonical id).
    conn = repo.connection
    async with conn.execute(
        "SELECT content, superseded_by FROM semantic_memory WHERE content = 'merge me'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row["superseded_by"] == ids["keep me"]
    await repo.close()


async def test_supersede_facts_empty_is_a_noop(repo: SqliteMemoryRepo) -> None:
    # Act / Assert: superseding nothing must not raise.
    await repo.supersede_facts({})
    await repo.close()


async def test_a_merge_never_relabels_either_fact(repo: SqliteMemoryRepo) -> None:
    """🔴 bob-g7t (соседний путь свёртки): дедуп НЕ трогает ось приватности.

    Консолидация отмывала метку, потому что СОЗДАВАЛА новую запись без неё. Дедуп ничего
    не создаёт: обе строки остаются на месте со своими метками, канониклом становится
    одна из них, а вторая просто перестаёт всплывать. Поэтому слияние приватного факта с
    публичным не может ни раскрыть приватное (содержимое никуда не копируется), ни
    засекретить публичное. Тест держит это свойство: сегодня оно выполняется
    «по построению» — ``select_active_facts`` даже не отдаёт метку, — и должно упасть,
    если кто-нибудь научит слияние писать ``visibility``.
    """
    # Arrange: a private fact and a public near-duplicate.
    await repo.save_fact(
        SemanticFact(ts=_ts(), category="user", content="лечит спину", visibility="owner_private")
    )
    await repo.save_fact(
        SemanticFact(ts=_ts(), category="user", content="лечит спину у врача", visibility="public")
    )
    rows = await repo.select_active_facts()
    ids = {str(r["content"]): int(str(r["id"])) for r in rows}

    # Act: merge the private one INTO the public canonical.
    await repo.supersede_facts({ids["лечит спину"]: ids["лечит спину у врача"]})

    # Assert: both rows keep exactly the label they were written with.
    conn = repo.connection
    async with conn.execute(
        "SELECT content, visibility FROM semantic_memory ORDER BY id"
    ) as cursor:
        stored = {str(row["content"]): row["visibility"] for row in await cursor.fetchall()}
    assert stored == {"лечит спину": "owner_private", "лечит спину у врача": "public"}
    await repo.close()
