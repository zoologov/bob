# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqliteSelfImprovementStore — per-persona персист правил (BOB-028 .1).

Round-trip: save_rule -> load восстанавливает все поля правила (наблюдение,
поправка, рычаг, величина, состояние, происхождение, created_at, evidence);
пустая персона даёт пустой кортеж; UPSERT; атомарный update_rule_state (включая
ключевой PROPOSED->APPROVED); per-persona изоляция; выживание после рестарта.

BOB-096 срез 1 — бухгалтерия ДОСТАВКИ предложения тоже переживает перезапуск:
``record_announce_attempt`` (атомарный инкремент попытки) и ``mark_announced``
(«owner услышал») round-trip'ятся через настоящий SQLite, а база, записанная до
BOB-096 (без этих колонок), догоняется идемпотентной миграцией и грузится без потерь.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.proactivity.adapters.self_improvement_store import (
    SqliteSelfImprovementStore,
)
from bob.proactivity.rule_announcement import (
    MAX_ANNOUNCE_ATTEMPTS,
    AnnounceStatus,
    announce_status,
)
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OTHER_PERSONA = "bender"
_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)

# Схема ``improvement_rule`` ДО BOB-096 — ровно так выглядит база owner'а, в которой
# лежат три его PROPOSED-правила. Пре-создаём таблицу этой формой, чтобы
# ``CREATE TABLE IF NOT EXISTS`` из schema.sql её не тронул: тогда путь до колонок —
# только guarded ALTER, то есть проверяется настоящая миграция, а не свежая схема.
_LEGACY_IMPROVEMENT_RULE_DDL = """
CREATE TABLE improvement_rule (
    persona_id  TEXT NOT NULL,
    id          TEXT NOT NULL,
    observation TEXT NOT NULL,
    adjustment  TEXT NOT NULL,
    lever       TEXT NOT NULL,
    magnitude   REAL NOT NULL,
    state       TEXT NOT NULL,
    origin      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    PRIMARY KEY (persona_id, id)
)
"""


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


def _rule(
    rid: str = "r1",
    *,
    lever: Lever = Lever.TONE,
    magnitude: float = 0.3,
    state: RuleState = RuleState.PROPOSED,
    origin: RuleOrigin = RuleOrigin.BOB_PROPOSED,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Замечаю, что отвечаю слишком сухо",
        adjustment="Добавить теплоты в тон",
        lever=lever,
        magnitude=magnitude,
        state=state,
        origin=origin,
        created_at=_NOW,
        evidence="Паттерн: короткие сухие ответы 5 раз подряд",
    )


async def test_load_empty_persona_yields_empty_tuple(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)

    assert await store.load(_PERSONA) == ()


async def test_save_rule_round_trips_all_fields(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    rule = _rule(lever=Lever.ADDRESSIVITY_BIAS, magnitude=0.42)

    await store.save_rule(_PERSONA, rule)
    loaded = await store.load(_PERSONA)

    assert loaded == (rule,)


async def test_load_reconstructs_multiple_rules_ordered(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule("a"))
    await store.save_rule(_PERSONA, _rule("b", lever=Lever.HUMOR))

    loaded = await store.load(_PERSONA)

    assert tuple(r.id for r in loaded) == ("a", "b")


async def test_save_rule_upserts(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule(state=RuleState.PROPOSED))

    await store.save_rule(_PERSONA, _rule(state=RuleState.APPROVED, magnitude=0.5))
    loaded = await store.load(_PERSONA)

    assert len(loaded) == 1
    assert loaded[0].state is RuleState.APPROVED
    assert loaded[0].magnitude == 0.5


async def test_update_rule_state_is_atomic(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule(state=RuleState.PROPOSED))

    await store.update_rule_state(_PERSONA, "r1", RuleState.APPROVED)
    loaded = await store.load(_PERSONA)

    assert loaded[0].state is RuleState.APPROVED


async def test_update_rule_state_through_pause(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule(state=RuleState.APPROVED))

    await store.update_rule_state(_PERSONA, "r1", RuleState.PAUSED)
    loaded = await store.load(_PERSONA)

    assert loaded[0].state is RuleState.PAUSED


async def test_personas_are_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule("r1"))
    await store.save_rule(_OTHER_PERSONA, _rule("r2"))

    mine = await store.load(_PERSONA)
    other = await store.load(_OTHER_PERSONA)

    assert tuple(r.id for r in mine) == ("r1",)
    assert tuple(r.id for r in other) == ("r2",)


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    rule = _rule(lever=Lever.PROACTIVITY, magnitude=0.25, state=RuleState.APPROVED)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteSelfImprovementStore(first).save_rule(_PERSONA, rule)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteSelfImprovementStore(second).load(_PERSONA)
    await second.close()

    assert loaded == (rule,)


# --- Бухгалтерия доставки предложения (BOB-096 срез 1) -----------------------


async def test_fresh_rule_has_no_announce_history(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule())

    loaded = await store.load(_PERSONA)

    assert loaded[0].announced is False
    assert loaded[0].announce_attempts == 0


async def test_record_announce_attempt_increments(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule())

    await store.record_announce_attempt(_PERSONA, "r1")
    await store.record_announce_attempt(_PERSONA, "r1")
    loaded = await store.load(_PERSONA)

    assert loaded[0].announce_attempts == 2
    assert loaded[0].announced is False


async def test_mark_announced_sets_the_flag(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule())

    await store.record_announce_attempt(_PERSONA, "r1")
    await store.mark_announced(_PERSONA, "r1")
    loaded = await store.load(_PERSONA)

    assert loaded[0].announced is True
    assert loaded[0].announce_attempts == 1
    assert announce_status(loaded[0]) is AnnounceStatus.DELIVERED


async def test_announce_bookkeeping_is_per_rule(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule("r1"))
    await store.save_rule(_PERSONA, _rule("r2"))

    await store.record_announce_attempt(_PERSONA, "r1")
    await store.mark_announced(_PERSONA, "r1")
    loaded = {rule.id: rule for rule in await store.load(_PERSONA)}

    assert loaded["r2"].announced is False
    assert loaded["r2"].announce_attempts == 0


async def test_announce_bookkeeping_is_per_persona(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule("r1"))
    await store.save_rule(_OTHER_PERSONA, _rule("r1"))

    await store.record_announce_attempt(_PERSONA, "r1")
    await store.mark_announced(_PERSONA, "r1")
    other = await store.load(_OTHER_PERSONA)

    assert other[0].announced is False
    assert other[0].announce_attempts == 0


async def test_announce_history_survives_restart(tmp_path: Path) -> None:
    # 🔴 Сердце дефекта: пометка жила в памяти процесса, и перезапуск проговаривал
    # владельцу всё заново. Здесь она переживает закрытие и повторное открытие базы.
    db = tmp_path / "bob.db"

    first = SqliteMemoryRepo(db)
    await first.initialize()
    first_store = SqliteSelfImprovementStore(first)
    await first_store.save_rule(_PERSONA, _rule())
    await first_store.record_announce_attempt(_PERSONA, "r1")
    await first_store.mark_announced(_PERSONA, "r1")
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteSelfImprovementStore(second).load(_PERSONA)
    await second.close()

    assert loaded[0].announced is True
    assert loaded[0].announce_attempts == 1


async def test_save_rule_upsert_preserves_announce_history(
    repo: SqliteMemoryRepo,
) -> None:
    # Правило пересохраняется (UPSERT) как объект, прочитанный из базы, — история
    # доставки едет вместе с ним и не обнуляется задним ходом.
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule())
    await store.record_announce_attempt(_PERSONA, "r1")
    await store.mark_announced(_PERSONA, "r1")

    reloaded = (await store.load(_PERSONA))[0]
    await store.save_rule(_PERSONA, reloaded)
    loaded = await store.load(_PERSONA)

    assert loaded[0].announced is True
    assert loaded[0].announce_attempts == 1


async def test_owner_state_move_keeps_announce_history(repo: SqliteMemoryRepo) -> None:
    store = SqliteSelfImprovementStore(repo)
    await store.save_rule(_PERSONA, _rule())
    await store.record_announce_attempt(_PERSONA, "r1")
    await store.mark_announced(_PERSONA, "r1")

    await store.update_rule_state(_PERSONA, "r1", RuleState.APPROVED)
    loaded = await store.load(_PERSONA)

    assert loaded[0].state is RuleState.APPROVED
    assert loaded[0].announced is True


# --- Миграция базы, записанной ДО BOB-096 ------------------------------------


def _write_legacy_rule_row(db: Path) -> None:
    """Создать базу с ДО-BOB-096 формой ``improvement_rule`` и одним PROPOSED-правилом."""
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as legacy:
        legacy.execute(_LEGACY_IMPROVEMENT_RULE_DDL)
        legacy.execute(
            "INSERT INTO improvement_rule (persona_id, id, observation, adjustment, "
            "lever, magnitude, state, origin, created_at, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _PERSONA,
                "rule-20260806083754-0",
                "Не учитывается адресат",
                "Обращаться по имени",
                Lever.ADDRESSIVITY_BIAS.value,
                0.3,
                RuleState.PROPOSED.value,
                RuleOrigin.BOB_PROPOSED.value,
                _NOW.isoformat(),
                "",
            ),
        )
        legacy.commit()


async def test_legacy_db_gains_announce_columns(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    _write_legacy_rule_row(db)

    repo = SqliteMemoryRepo(db)
    await repo.initialize()
    loaded = await SqliteSelfImprovementStore(repo).load(_PERSONA)
    await repo.close()

    # Существующая строка грузится, а не роняет загрузку, и читается как «ещё не
    # проговорено» — то есть попадёт владельцу ровно один раз, а не бесконечно.
    assert len(loaded) == 1
    assert loaded[0].id == "rule-20260806083754-0"
    assert loaded[0].announced is False
    assert loaded[0].announce_attempts == 0
    assert announce_status(loaded[0]) is AnnounceStatus.PENDING


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    _write_legacy_rule_row(db)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    store = SqliteSelfImprovementStore(first)
    await store.record_announce_attempt(_PERSONA, "rule-20260806083754-0")
    await first.close()

    # Повторный запуск процесса над той же базой: миграция — чистый no-op, и
    # накопленная бухгалтерия доставки не сбрасывается.
    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteSelfImprovementStore(second).load(_PERSONA)
    await second.close()

    assert loaded[0].announce_attempts == 1


async def test_legacy_row_is_announceable_then_capped(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    _write_legacy_rule_row(db)
    repo = SqliteMemoryRepo(db)
    await repo.initialize()
    store = SqliteSelfImprovementStore(repo)

    for _ in range(MAX_ANNOUNCE_ATTEMPTS):
        await store.record_announce_attempt(_PERSONA, "rule-20260806083754-0")
    loaded = await store.load(_PERSONA)
    await repo.close()

    assert announce_status(loaded[0]) is AnnounceStatus.UNDELIVERED
