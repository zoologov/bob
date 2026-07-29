# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the staleness врезка WIRING scenarios (BOB-066 Срез W.3).

Binds ``staleness_wiring.feature`` to the wired handler harness (the real reply path + a scripted
judge + a scope whose ``peek_arrivals`` returns what landed during generation). The scenarios pin
the observable wired contract through the outgoing boundary: a now-redundant draft drops to a
like; 🔴🔴 a fresh direct question is never dropped; with the врезка off the reply is sent as
before.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.staleness_wiring_harness import (
    StalenessWiringOutcome,
    run_staleness_turn,
)

scenarios("../features/staleness_wiring.feature")


@dataclass(slots=True)
class _State:
    enabled: bool = False
    outcome: StalenessWiringOutcome | None = None


@given("включена врезка staleness", target_fixture="staleness_state")
def staleness_on() -> _State:
    return _State(enabled=True)


@given("врезка staleness ВЫКЛючена", target_fixture="staleness_state")
def staleness_off() -> _State:
    return _State(enabled=False)


@when("пока Боб дописывал, на тот же вопрос уже ответил другой участник")
def answered_by_other(staleness_state: _State) -> None:
    staleness_state.outcome = asyncio.run(
        run_staleness_turn(enabled=staleness_state.enabled, answered_by_other=True)
    )


@when("пока Боб дописывал, прилетел свежий прямой вопрос к нему")
def fresh_direct_question(staleness_state: _State) -> None:
    # 🔴🔴 Even with the original point answered, a fresh direct question must never be dropped.
    staleness_state.outcome = asyncio.run(
        run_staleness_turn(
            enabled=staleness_state.enabled,
            answered_by_other=True,
            new_direct_question=True,
        )
    )


@then("Боб не отправляет устаревший дубль, а ставит реакцию")
def dropped_to_like(staleness_state: _State) -> None:
    outcome = staleness_state.outcome
    assert outcome is not None
    assert outcome.liked, "ожидалась реакция на устаревший черновик"
    assert not outcome.replied, "устаревший дубль не должен уходить в чат"


@then("Боб всё равно отвечает репликой, а не молчит лайком")
def still_replies(staleness_state: _State) -> None:
    outcome = staleness_state.outcome
    assert outcome is not None
    assert outcome.replied, "свежий прямой вопрос обязан быть отвечен (INV-1)"
    assert not outcome.liked, "свежий прямой вопрос не роняется в лайк"


@then("Боб отправляет реплику как обычно")
def replies_as_usual(staleness_state: _State) -> None:
    outcome = staleness_state.outcome
    assert outcome is not None
    assert outcome.replied, "при выключенной врезке Боб отвечает как раньше"
    assert not outcome.liked
