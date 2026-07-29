# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the intake burst/focus acceptance scenarios (BOB-066 Срез 2.1).

Binds ``intake_burst.feature`` to the real :class:`ChatDispatcher` seam via
``intake_harness`` — the scenarios read as behaviour, the harness drives the real intake
decoupling. Each async drive runs inside the When step via ``asyncio.run`` (pytest-bdd
generates a sync test), mirroring the other acceptance steps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.intake_harness import (
    BOB_ID,
    IntakeObservations,
    drive_focused_message_in_a_burst,
    drive_ordered_burst_without_stalling,
)

scenarios("../features/intake_burst.feature")


@dataclass(slots=True)
class _BurstContext:
    """The slate the burst scenario's steps share."""

    observations: IntakeObservations = field(default_factory=IntakeObservations)


@given("Боб занят генерацией предыдущего хода", target_fixture="burst_context")
def bob_is_generating() -> _BurstContext:
    return _BurstContext()


@given("Боб слушает шумный групповой чат", target_fixture="burst_context")
def bob_listens_to_a_noisy_chat() -> _BurstContext:
    return _BurstContext()


@when("участник быстро отправляет три сообщения подряд")
def participant_sends_a_rapid_burst(burst_context: _BurstContext) -> None:
    burst_context.observations = asyncio.run(drive_ordered_burst_without_stalling())


@when("во всплеске ambient-реплик приходит прямое обращение к Бобу")
def a_focused_message_arrives_in_a_burst(burst_context: _BurstContext) -> None:
    burst_context.observations = asyncio.run(drive_focused_message_in_a_burst())


@then("приём каждого сообщения возвращается немедленно, не дожидаясь генерации")
def submit_returned_before_generation(burst_context: _BurstContext) -> None:
    assert burst_context.observations.submit_returned_before_generation, (
        "приём заблокировался на генерации (поллинг застрял)"
    )


@then("все три сообщения обрабатываются строго по порядку прибытия")
def burst_handled_in_arrival_order(burst_context: _BurstContext) -> None:
    assert burst_context.observations.handled_order == [1, 2, 3]


@then("Боб отвечает на фокусное обращение")
def bob_answers_the_focused_message(burst_context: _BurstContext) -> None:
    # message_id 2 is the «Боб, …» direct address in the burst.
    assert 2 in burst_context.observations.answered_message_ids, (
        "фокусное обращение к Бобу осталось без ответа"
    )
    assert BOB_ID  # identity was resolved for the focus check


@then("ни одно сообщение всплеска не потеряно")
def no_burst_message_is_lost(burst_context: _BurstContext) -> None:
    assert burst_context.observations.handled_order == [1, 2, 3]
