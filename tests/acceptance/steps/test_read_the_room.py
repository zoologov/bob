# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the reflective «read the room» acceptance scenarios (BOB-066 2.2).

Binds the Gherkin steps of ``read_the_room.feature`` to the reflective fake-gateway
harness (``presence.reflective`` ON, the room-judge scripted to IGNORE). The two
scenarios pin the observable focus/periphery contract through the boundary:

* a direct address ALWAYS replies (INV-1), even though the judge would ignore;
* an ambient low-salience turn stays silent (no reply, no reaction).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.reflective_harness import run_reflective_turn

if TYPE_CHECKING:
    from tests.acceptance.conftest import ScenarioContext

# The scripted reply Bob composes on the FOCUS path (asserted as the observable reply).
_SCRIPTED_REPLY = "Зонды? Обожаю эту тему, давай расскажу…"

scenarios("../features/read_the_room.feature")


@given("Боб запущен с включённой рефлексией, а судья комнаты хочет промолчать")
def reflective_bob_ready(scenario_context: ScenarioContext) -> None:
    """Readiness — a clean slate; the turn boots the graph in the When step."""
    assert not scenario_context.gateway.replied


@when(parsers.parse('участник напрямую обращается к Бобу: "{text}"'))
def participant_addresses_bob(scenario_context: ScenarioContext, text: str) -> None:
    """Drive a FOCUS turn (mentions_bob=True) end-to-end through the reflective graph."""
    scenario_context.gateway = asyncio.run(
        run_reflective_turn(
            scenario_context.tmp_path, text=text, mentions_bob=True, reply=_SCRIPTED_REPLY
        )
    )


@when(parsers.parse('участник роняет реплику в воздух: "{text}"'))
def participant_speaks_to_the_air(scenario_context: ScenarioContext, text: str) -> None:
    """Drive an AMBIENT periphery turn (mentions_bob=False) end-to-end."""
    scenario_context.gateway = asyncio.run(
        run_reflective_turn(
            scenario_context.tmp_path, text=text, mentions_bob=False, reply=_SCRIPTED_REPLY
        )
    )


@then("Боб отправляет ответную реплику в этот чат")
def bob_replies(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.replied, "Боб промолчал на прямое обращение (INV-1)"


@then("Боб не отправляет реплику и не ставит реакцию")
def bob_stays_silent(scenario_context: ScenarioContext) -> None:
    assert not scenario_context.gateway.replied, "Боб влез в тихий общий фон"
    assert not scenario_context.gateway.reactions, "Боб поставил реакцию на тихий фон"
