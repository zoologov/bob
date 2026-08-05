# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-090.C2 — точное происхождение эпизода (чат + топик).

Покрывает аддитивные колонки ``episodic_log.origin_chat_id`` / ``origin_topic_id``
(свежая база + идемпотентная миграция базы, созданной без них), запись адреса и
чтение его обратно через существующую дверь ``load_episodes``.

🔴 Главное здесь — семантика ``NULL``. Для ``visibility`` (BOB-066 2.6) NULL читается
как «публично» — сознательный fail-open ради сквозной памяти. Для адреса такого чтения
НЕТ и быть не должно: NULL означает «источник неизвестен». Старых строк в живой базе
больше двух тысяч, и превращать «не знаю где» в утверждение о месте — это ровно тот
дефект (эпизод 3092), который эпик и чинит.

🔴 И адрес не силосит recall: сквозная память (BOB-082) — Боб один разум, поэтому
эпизоды из разных чатов припоминаются вместе, а строки recall для эпизода с адресом и
без адреса совпадают байт-в-байт.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.entities import EpisodicEvent

if TYPE_CHECKING:
    from pathlib import Path

_DM_CHAT = 4242
_GROUP_CHAT = -1001234567890
_GROUP_TOPIC = 77


def _ts() -> datetime:
    return datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


async def _column_names(db_path: Path, table: str) -> set[str]:
    conn = await aiosqlite.connect(db_path)
    try:
        async with conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return {str(row[1]) for row in rows}


# --- Схема (свежая база) ------------------------------------------------------


async def test_fresh_db_has_origin_columns(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.close()

    columns = await _column_names(tmp_path / "bob.db", "episodic_log")
    assert "origin_chat_id" in columns
    assert "origin_topic_id" in columns


# --- Миграция (база, созданная без колонок) -----------------------------------


async def _legacy_db(db_path: Path) -> None:
    """Создать базу по СТАРОЙ схеме (без колонок адреса) с одной живой строкой."""
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


async def test_migration_adds_origin_columns_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "bob.db"
    await _legacy_db(db_path)

    # Act: инициализация ДВАЖДЫ поверх старой базы (guarded ALTER идемпотентен).
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.initialize()
    await repo.close()

    columns = await _column_names(db_path, "episodic_log")
    assert "origin_chat_id" in columns
    assert "origin_topic_id" in columns


async def test_migration_keeps_every_legacy_row(tmp_path: Path) -> None:
    # Миграция аддитивна: ни одна старая запись не теряется и не переписывается.
    db_path = tmp_path / "bob.db"
    await _legacy_db(db_path)

    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    assert [str(e["content"]) for e in episodes] == ["legacy turn"]


async def test_legacy_row_origin_reads_as_unknown_not_public(tmp_path: Path) -> None:
    # 🔴 Сердце беады: у старой записи адреса НЕТ, и он остаётся NULL — «не знаю где».
    # Ни общий чат, ни личка, ни ноль: никакой подстановки.
    db_path = tmp_path / "bob.db"
    await _legacy_db(db_path)

    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    legacy = next(e for e in episodes if str(e["content"]) == "legacy turn")
    assert legacy["origin_chat_id"] is None
    assert legacy["origin_topic_id"] is None


async def test_unknown_origin_never_borrows_a_neighbours_address(tmp_path: Path) -> None:
    # Рядом лежит эпизод с известным адресом — старая запись всё равно остаётся без
    # адреса: «неизвестно» не заполняется ближайшим известным местом.
    db_path = tmp_path / "bob.db"
    await _legacy_db(db_path)

    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "vova: привет комнате\nbob: привет",
            "origin_chat_id": _GROUP_CHAT,
            "origin_topic_id": _GROUP_TOPIC,
        }
    )
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    legacy = next(e for e in episodes if str(e["content"]) == "legacy turn")
    fresh = next(e for e in episodes if "привет комнате" in str(e["content"]))
    assert legacy["origin_chat_id"] is None
    assert fresh["origin_chat_id"] == _GROUP_CHAT


# --- Запись адреса ------------------------------------------------------------


async def test_save_episode_persists_the_exact_address(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "vova: в топике\nbob: ага",
            "origin_chat_id": _GROUP_CHAT,
            "origin_topic_id": _GROUP_TOPIC,
        }
    )
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    assert episodes[0]["origin_chat_id"] == _GROUP_CHAT
    assert episodes[0]["origin_topic_id"] == _GROUP_TOPIC


async def test_save_episode_entity_carries_the_address(tmp_path: Path) -> None:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_episode_entity(
        EpisodicEvent(
            ts=_ts(),
            event_type="message",
            content="vova: наедине\nbob: понял",
            origin_chat_id=_DM_CHAT,
        )
    )
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    # Личка: чат известен, топика нет — и это «топика нет», а не «чат неизвестен».
    assert episodes[0]["origin_chat_id"] == _DM_CHAT
    assert episodes[0]["origin_topic_id"] is None


async def test_episode_without_an_address_stays_unknown(tmp_path: Path) -> None:
    # Тик, дайджест, любая запись без входящего сообщения — источник неизвестен.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    await repo.save_episode(
        {"ts": _ts().isoformat(), "event_type": "reflection", "content": "подумалось"}
    )
    episodes = await repo.load_episodes(limit=10)
    await repo.close()

    assert episodes[0]["origin_chat_id"] is None
    assert episodes[0]["origin_topic_id"] is None


# --- 🔴 Не силосить: адрес — метаданные, не фильтр recall ----------------------


async def test_recall_spans_chats_the_address_filters_nothing(tmp_path: Path) -> None:
    # Сквозная память (BOB-082): Боб один разум. Эпизод из лички и эпизод из группы
    # припоминаются ВМЕСТЕ — адрес ничего не отсекает.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "vova: обсудили рефакторинг наедине",
            "origin_chat_id": _DM_CHAT,
        }
    )
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "норман: обсудили рефакторинг при всех",
            "origin_chat_id": _GROUP_CHAT,
            "origin_topic_id": _GROUP_TOPIC,
        }
    )

    recalled = await Fts5MemoryRecall(repo).recall("рефакторинг", k=5)
    await repo.close()

    contents = {str(item["content"]) for item in recalled}
    assert contents == {
        "vova: обсудили рефакторинг наедине",
        "норман: обсудили рефакторинг при всех",
    }


async def _recalled_rows(db_path: Path, episode: dict[str, object]) -> list[dict[str, object]]:
    """Строки recall для одного сохранённого эпизода (реальный FTS5-путь)."""
    repo = SqliteMemoryRepo(db_path)
    await repo.initialize()
    await repo.save_episode(episode)
    rows = [dict(item) for item in await Fts5MemoryRecall(repo).recall("рефакторинг", k=5)]
    await repo.close()
    return rows


async def test_recall_rows_are_byte_identical_with_and_without_an_address(
    tmp_path: Path,
) -> None:
    # 🔴 Флага у записи адреса нет, поэтому байт-в-байт доказывается РАВЕНСТВОМ: то,
    # что уходит в промпт (строки recall), совпадает посимвольно для эпизода с адресом
    # и без него. Адрес — метаданные хранения, он не течёт в поведение.
    base: dict[str, object] = {
        "ts": _ts().isoformat(),
        "event_type": "message",
        "content": "vova: обсудили рефакторинг\nbob: помню",
    }

    with_address = await _recalled_rows(
        tmp_path / "with.db",
        {**base, "origin_chat_id": _GROUP_CHAT, "origin_topic_id": _GROUP_TOPIC},
    )
    without_address = await _recalled_rows(tmp_path / "without.db", dict(base))

    assert with_address == without_address
