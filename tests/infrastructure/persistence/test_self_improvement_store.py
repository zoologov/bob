# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqliteSelfImprovementStore — per-persona персист правил (BOB-028 .1).

Round-trip: save_rule -> load восстанавливает все поля правила (наблюдение,
поправка, рычаг, величина, состояние, происхождение, created_at, evidence);
пустая персона даёт пустой кортеж; UPSERT; атомарный update_rule_state (включая
ключевой PROPOSED->APPROVED); per-persona изоляция; выживание после рестарта.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.proactivity.adapters.self_improvement_store import (
    SqliteSelfImprovementStore,
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
