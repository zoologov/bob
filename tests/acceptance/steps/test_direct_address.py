# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the direct-address acceptance scenario (BOB-066 Срез 0).

Binds the Gherkin steps of ``direct_address.feature`` to the fake-gateway harness.
This is the reference wiring that proves the pytest-bdd + fake-gateway layer runs
end-to-end; later slices add the INV-1…9 + PRD A/B/C/D scenarios on the same harness.

The scenario is synchronous (pytest-bdd generates a sync test), so the async turn is
driven via ``asyncio.run`` inside the When step — no event loop is active around it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.fake_gateway import run_turn

if TYPE_CHECKING:
    from tests.acceptance.conftest import ScenarioContext

# The scripted Tier-1 answer Bob composes when he chooses to reply — asserted, verbatim,
# as the observable reply that reaches the participant through the gateway.
_SCRIPTED_REPLY = "Конечно — зонды это мои любимые железки, вот что важно…"

scenarios("../features/direct_address.feature")


@given("Боб запущен и слушает свой топик")
def bob_is_running(scenario_context: ScenarioContext) -> None:
    """Readiness — the fresh temp db + soul are established by the fixture; the turn
    itself boots the graph in the When step, so this step just asserts a clean slate."""
    assert not scenario_context.gateway.replied


@when(parsers.parse('участник напрямую обращается к Бобу: "{text}"'))
def participant_addresses_bob(scenario_context: ScenarioContext, text: str) -> None:
    """Drive one direct-address turn end-to-end through the real graph on fakes."""
    scenario_context.gateway = asyncio.run(
        run_turn(scenario_context.tmp_path, text=text, reply=_SCRIPTED_REPLY)
    )


@then("Боб отправляет ответную реплику в этот чат")
def bob_replies(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.replied, "Боб промолчал на прямое обращение"


@then("реплика доходит до участника через шлюз")
def reply_reaches_participant(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.last_reply == _SCRIPTED_REPLY
