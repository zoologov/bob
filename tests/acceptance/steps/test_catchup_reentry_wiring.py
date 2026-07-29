# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the catch-up re-entry WIRING scenarios (BOB-066 Срез W.3).

Binds ``catchup_reentry_wiring.feature`` to the wired dispatcher harness (the real
``ChatDispatcher`` + ``CatchUpReentry`` + a scripted handler that records what it handled). The
scenarios pin the observable wired contract: 🔴 after an away period a backlogged direct question
is answered in ONE pass while ambient asides beyond budget are skimmed; with the flag off the
worker replays every message.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.catchup_reentry_wiring_harness import (
    CatchUpObservations,
    run_reentry,
)

scenarios("../features/catchup_reentry_wiring.feature")


@dataclass(slots=True)
class _State:
    enabled: bool = False
    observations: CatchUpObservations | None = None


@given("включён догоняющий на входе", target_fixture="catchup_state")
def catchup_on() -> _State:
    return _State(enabled=True)


@given("догоняющий на входе ВЫКЛючен", target_fixture="catchup_state")
def catchup_off() -> _State:
    return _State(enabled=False)


@when("после долгого отсутствия в чате накопился завал с прямым вопросом к Бобу")
def a_backlog_after_absence(catchup_state: _State) -> None:
    catchup_state.observations = asyncio.run(run_reentry(enabled=catchup_state.enabled))


@then("Боб отвечает на прямой вопрос одним проходом, а лишнюю болтовню пролистывает")
def one_pass_answers_the_focal(catchup_state: _State) -> None:
    obs = catchup_state.observations
    assert obs is not None
    # Message 3 is the direct address (mentions Bob) in the backlog — always answered (INV-1).
    assert 3 in obs.handled, "прямой вопрос обязан быть отвечен на входе (INV-1)"
    # The ambient asides beyond budget 1 are skimmed, not replayed one-by-one.
    skimmed = {2, 4, 5} - set(obs.handled)
    assert skimmed, "фоновая болтовня сверх бюджета должна быть пролистана"


@then("Боб обрабатывает каждое сообщение как раньше")
def replays_every_message(catchup_state: _State) -> None:
    obs = catchup_state.observations
    assert obs is not None
    # Off → every backlog message is handled (plus the first passthrough message).
    assert {1, 2, 3, 4, 5} <= set(obs.handled), "при выключенном флаге проигрываются все"
