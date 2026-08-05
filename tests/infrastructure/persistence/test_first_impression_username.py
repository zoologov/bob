# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты хранения ``@username`` на ростере (BOB-090.B3).

Корень эпизода 3088 («@Норман» вместо ``@NormanGri``): ник не хранился НИГДЕ, так что
тег было неоткуда взять. Здесь проверяется хранилище:

* колонка ``first_impression.username`` появляется и на свежей базе, и на уже живущей
  (guarded ALTER по образцу ``display_name``, BOB-080), аддитивно и идемпотентно;
* легаси-строка читается как ``None`` — «ника не знаю», а не выдуманный;
* 🔴 ник ОБНОВЛЯЕТСЯ у уже знакомого человека, в отличие от заметки и первой встречи:
  впечатление формируется однажды, а ник в Telegram человек меняет когда захочет. Без
  этого 2344 уже знакомых человека остались бы без тега навсегда.
* известный ник не затирается ходом, который ник не принёс.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from pathlib import Path

_SENDER = 4242
_SEEN = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def _columns(repo: SqliteMemoryRepo) -> set[str]:
    async with repo.connection.execute("PRAGMA table_info(first_impression)") as cursor:
        rows = await cursor.fetchall()
    return {str(row[1]) for row in rows}


async def test_a_fresh_database_has_the_username_column(repo: SqliteMemoryRepo) -> None:
    assert "username" in await _columns(repo)


async def test_the_username_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    impression = FirstImpression(
        sender_id=_SENDER,
        first_seen_at=_SEEN,
        note="Норман — кто-то из знакомых",
        display_name="Норман",
        username="NormanGri",
    )

    await store.save(impression)

    assert await store.load(_SENDER) == impression


async def test_a_known_person_gets_their_handle_filled_in_later(
    repo: SqliteMemoryRepo,
) -> None:
    # 🔴 Живой случай: человек знаком давно (строка есть), ника у неё нет. Формирование
    # впечатления «однажды» не должно означать «ника не будет никогда».
    store = SqliteFirstImpressionStore(repo)
    await store.save(
        FirstImpression(
            sender_id=_SENDER, first_seen_at=_SEEN, note="Норман — знакомый"
        )
    )

    await store.save(
        FirstImpression(
            sender_id=_SENDER,
            first_seen_at=_LATER,
            note="другая заметка",
            display_name="другое имя",
            username="NormanGri",
        )
    )

    loaded = await store.load(_SENDER)
    assert loaded is not None
    assert loaded.username == "NormanGri"
    # …и при этом впечатление осталось сформированным ОДНАЖДЫ.
    assert loaded.first_seen_at == _SEEN
    assert loaded.note == "Норман — знакомый"
    assert loaded.display_name is None


async def test_a_changed_handle_is_refreshed(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    await store.save(
        FirstImpression(
            sender_id=_SENDER, first_seen_at=_SEEN, note="Норман", username="old_handle"
        )
    )

    await store.save(
        FirstImpression(
            sender_id=_SENDER, first_seen_at=_SEEN, note="Норман", username="NormanGri"
        )
    )

    loaded = await store.load(_SENDER)
    assert loaded is not None
    assert loaded.username == "NormanGri"


async def test_a_turn_without_a_handle_never_erases_a_known_one(
    repo: SqliteMemoryRepo,
) -> None:
    # Апдейт без username (Telegram его не обязан присылать) не должен стирать знание.
    store = SqliteFirstImpressionStore(repo)
    await store.save(
        FirstImpression(
            sender_id=_SENDER, first_seen_at=_SEEN, note="Норман", username="NormanGri"
        )
    )

    await store.save(
        FirstImpression(sender_id=_SENDER, first_seen_at=_SEEN, note="Норман")
    )

    loaded = await store.load(_SENDER)
    assert loaded is not None
    assert loaded.username == "NormanGri"


async def test_a_legacy_row_reads_as_no_handle(repo: SqliteMemoryRepo) -> None:
    await repo.connection.execute(
        "INSERT INTO first_impression (sender_id, first_seen_at, note) VALUES (?, ?, ?)",
        (_SENDER, _SEEN.isoformat(), "Паша — уже виделись"),
    )
    await repo.connection.commit()

    loaded = await SqliteFirstImpressionStore(repo).load(_SENDER)

    assert loaded is not None
    assert loaded.username is None


async def test_recent_carries_the_handle(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    await store.save(
        FirstImpression(
            sender_id=_SENDER,
            first_seen_at=_SEEN,
            note="Норман",
            display_name="Норман",
            username="NormanGri",
        )
    )

    recent = await store.recent(limit=5)

    assert [person.username for person in recent] == ["NormanGri"]


async def test_the_migration_is_additive_on_a_pre_existing_database(
    tmp_path: Path,
) -> None:
    # База БЕЗ колонки (как живая): строка заводится напрямую, потом initialize().
    db = tmp_path / "legacy.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "CREATE TABLE first_impression ("
            "sender_id INTEGER PRIMARY KEY, first_seen_at TEXT NOT NULL, "
            "note TEXT NOT NULL, display_name TEXT)"
        )
        await conn.execute(
            "INSERT INTO first_impression VALUES (?, ?, ?, ?)",
            (_SENDER, _SEEN.isoformat(), "Норман — знакомый", "Норман"),
        )
        await conn.commit()

    repo = SqliteMemoryRepo(db)
    await repo.initialize()
    # Идемпотентность: вторая инициализация — чистый no-op.
    await repo.initialize()
    loaded = await SqliteFirstImpressionStore(repo).load(_SENDER)
    columns = await _columns(repo)
    await repo.close()

    assert "username" in columns
    assert loaded is not None
    assert loaded.note == "Норман — знакомый"  # ни одна строка не потеряна и не тронута
    assert loaded.username is None  # ник не выдуман из имени
