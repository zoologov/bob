# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the rhythm consumption WIRING scenarios (BOB-066 Срез W).

Binds ``presence_rhythm_wiring.feature`` to the wired fake-gateway harness (reflective ON, the
room-judge scripted to REPLY, Bob's airtime hogged). The scenarios pin the observable wired
contract through the boundary:

* an AMBIENT barge is throttled to silence by the share-of-voice ceiling when Bob has hogged
  the room (rhythm ON);
* a DIRECT address bypasses the ceiling and replies (INV-1);
* with rhythm OFF the same ambient turn still replies (byte-identical regression).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.rhythm_wiring_harness import (
    run_unwired_ambient_turn,
    run_wired_ambient_turn,
    run_wired_focus_turn,
)

if TYPE_CHECKING:
    from tests.acceptance.conftest import ScenarioContext

scenarios("../features/presence_rhythm_wiring.feature")


@given("ритм-слой включён, а Боб наговорил почти весь недавний эфир")
def rhythm_on_and_bob_hogged(scenario_context: ScenarioContext) -> None:
    """Readiness — the hogged airtime is seeded by the harness in the When step."""
    scenario_context.rhythm_enabled = True
    assert not scenario_context.gateway.replied


@given("ритм-слой ВЫКЛючен, а Боб наговорил почти весь недавний эфир")
def rhythm_off_and_bob_hogged(scenario_context: ScenarioContext) -> None:
    """Readiness — same hogged airtime, but the rhythm layer stays inert."""
    scenario_context.rhythm_enabled = False
    assert not scenario_context.gateway.replied


@when(parsers.parse('участник роняет реплику в воздух: "{text}"'))
def participant_speaks_to_the_air(scenario_context: ScenarioContext, text: str) -> None:
    """Drive an AMBIENT periphery turn (mentions_bob=False) with rhythm on/off."""
    runner = (
        run_wired_ambient_turn
        if scenario_context.rhythm_enabled
        else run_unwired_ambient_turn
    )
    scenario_context.gateway = asyncio.run(
        runner(scenario_context.tmp_path, text=text)
    )


@when(parsers.parse('участник напрямую обращается к Бобу: "{text}"'))
def participant_addresses_bob(scenario_context: ScenarioContext, text: str) -> None:
    """Drive a FOCUS turn (mentions_bob=True) — the ceiling is bypassed (INV-1)."""
    scenario_context.gateway = asyncio.run(
        run_wired_focus_turn(scenario_context.tmp_path, text=text)
    )


@then("Боб не отправляет реплику")
def bob_stays_silent(scenario_context: ScenarioContext) -> None:
    assert not scenario_context.gateway.replied, "Боб влез в эфир, перебрав долю эфира"


@then("Боб отправляет ответную реплику")
def bob_replies(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.replied, "Боб промолчал (ожидался ответ)"
