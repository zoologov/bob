# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the RoomMood-в-тоне consumption WIRING scenarios (BOB-066 Срез W.2).

Binds ``room_mood_wiring.feature`` to the wired fake-gateway harness (reflective ON, the
room-judge scripted to REPLY on a HEAVY/heated room). The scenarios pin the observable wired
contract through the LLM boundary:

* a heavy/heated room folds the «сбавь игривость» tone line into Bob's compose system prompt
  (room-mood ON);
* with the flag OFF the same heavy-room reply carries NO room tone line (byte-identical).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.room_mood_wiring_harness import run_heavy_room_turn

if TYPE_CHECKING:
    from tests.acceptance.conftest import ScenarioContext

scenarios("../features/room_mood_wiring.feature")


@given("вшит слой настроения комнаты, а комната читается тяжёлой и накалённой")
def room_mood_on(scenario_context: ScenarioContext) -> None:
    """Readiness — the heavy-room reading is scripted by the harness in the When step."""
    scenario_context.room_mood_enabled = True
    assert not scenario_context.gateway.replied


@given("слой настроения комнаты ВЫКЛючен, а комната читается тяжёлой и накалённой")
def room_mood_off(scenario_context: ScenarioContext) -> None:
    """Readiness — same heavy-room reading, but the room-mood seam stays inert."""
    scenario_context.room_mood_enabled = False
    assert not scenario_context.gateway.replied


@when(parsers.parse('в живой группе участник роняет тяжёлую реплику в воздух: "{text}"'))
def participant_drops_a_heavy_line(scenario_context: ScenarioContext, text: str) -> None:
    """Drive a multi-party AMBIENT periphery turn with the room-mood seam on/off."""
    outcome = asyncio.run(
        run_heavy_room_turn(
            scenario_context.tmp_path,
            text=text,
            room_mood_enabled=scenario_context.room_mood_enabled,
        )
    )
    scenario_context.gateway = outcome.gateway
    scenario_context.tone_line_folded = outcome.tone_line_folded


@then("Боб отправляет ответную реплику")
def bob_replies(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.replied, "Боб промолчал (ожидался ответ)"


@then("в голос вплетена директива сбавить игривость")
def tone_line_folded(scenario_context: ScenarioContext) -> None:
    assert scenario_context.tone_line_folded, "директива «сбавь игривость» не вплетена в голос"


@then("в голос НЕ вплетена директива сбавить игривость")
def tone_line_not_folded(scenario_context: ScenarioContext) -> None:
    assert not scenario_context.tone_line_folded, (
        "директива комнаты просочилась в голос при выключенном флаге"
    )
