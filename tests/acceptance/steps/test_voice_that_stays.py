# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шаги сценариев «голос, который остаётся» (BOB-096, срезы 3 и 4).

Связывают ``voice_that_stays.feature`` с
:mod:`tests.acceptance.voice_that_stays_harness`, который гоняет настоящие двери через
настоящую фабрику провайдеров и настоящий HTTP. Утверждения — только о наблюдаемом
снаружи: что осело в памяти Боба, что пришло владельцу, сколько раз спросили дублёра и
какие сырые тела запросов пересекли границу к модели.

Сценарии синхронные (pytest-bdd), поэтому ход гоняется через ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.voice_that_stays_harness import (
    DoorOutcome,
    machine_canon,
    prose_canon,
    run_door,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/voice_that_stays.feature")


@dataclass(slots=True)
class _DoorContext:
    """Доска сценария: своя база, своё состояние облака, свой исход хода."""

    db_root: Path
    cloud_is_up: bool = True
    outcome: DoorOutcome = field(default_factory=DoorOutcome)


@pytest.fixture
def door_context(tmp_path: Path) -> _DoorContext:
    return _DoorContext(db_root=tmp_path)


def _seen_by_the_model(context: _DoorContext) -> str:
    """Всё, что реально уехало модели, — сырыми телами запросов с обеих сторон."""
    return f"{context.outcome.cloud_saw}\n{context.outcome.understudy_saw}"


# --- Дано: живо ли облако -----------------------------------------------------------


@given("облако отвечает")
def cloud_is_up(door_context: _DoorContext) -> None:
    door_context.cloud_is_up = True


@given("облако лежит, работает только локальный дублёр")
def cloud_is_down(door_context: _DoorContext) -> None:
    # Оба облачных тира стоят на мёртвом порту: соединение отвергает ядро ОС, то есть
    # отвал настоящий (в ту ночь легли оба — они на одном хосте).
    door_context.cloud_is_up = False


# --- Когда: один ход выбранной дверью -----------------------------------------------


@when(parsers.parse("Боб проходит дверью «{door}»"))
def bob_goes_through_the_door(door_context: _DoorContext, door: str) -> None:
    door_context.outcome = asyncio.run(
        run_door(door, cloud_is_up=door_context.cloud_is_up, db_root=door_context.db_root)
    )


# --- Тогда: что пересекло границу ----------------------------------------------------


@then("в задании модели стоит запрет говорить за GUPPI")
def the_prompt_carries_the_prose_canon(door_context: _DoorContext) -> None:
    assert prose_canon() in _seen_by_the_model(door_context)


@then("в задании модели стоит запрет в машинной форме")
def the_prompt_carries_the_machine_canon(door_context: _DoorContext) -> None:
    assert machine_canon() in _seen_by_the_model(door_context)


@then("прозаических указаний о речи в задании нет")
def the_prompt_carries_no_prose_instructions(door_context: _DoorContext) -> None:
    # Иначе «канон везде» молча сломал бы контракт ответа этой двери.
    assert prose_canon() not in _seen_by_the_model(door_context)


@then("в задании модели нет ни слова о GUPPI")
def the_prompt_says_nothing_about_guppi(door_context: _DoorContext) -> None:
    seen = _seen_by_the_model(door_context)
    assert prose_canon() not in seen
    assert machine_canon() not in seen


@then("запись родилась")
def something_was_born(door_context: _DoorContext) -> None:
    # Анти-вакуум: без этого «канон доехал» ничего не значило бы — дверь могла бы
    # вообще не открыться.
    assert door_context.outcome.born, door_context.outcome


@then("ничего не родилось")
def nothing_was_born(door_context: _DoorContext) -> None:
    assert door_context.outcome.born == (), door_context.outcome


@then("дублёра не спрашивали")
def the_understudy_was_never_asked(door_context: _DoorContext) -> None:
    assert door_context.outcome.understudy_calls == 0


@then("дублёра спросили один раз")
def the_understudy_answered_once(door_context: _DoorContext) -> None:
    assert door_context.outcome.understudy_calls == 1


@then("ход честно отказал")
def the_turn_failed_honestly(door_context: _DoorContext) -> None:
    # Молчание вместо чужого голоса — это отказ, а не тихая деградация: тик падает,
    # супервизор его изолирует, владелец видит отвал в логе.
    assert door_context.outcome.failed != ""


@then("вердикт вернулся")
def the_verdict_came_back(door_context: _DoorContext) -> None:
    assert door_context.outcome.verdict
