# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the reply-to acceptance scenarios (BOB-066 Срез 1.1).

Binds ``reply_to.feature`` to the fake-gateway harness: the SAME direct address to
Bob is driven once in a multi-party thread and once in a 1:1, and the scenarios
witness — through the outgoing boundary (aiogram ``ReplyParameters``, captured as
``FakeGateway.reply_targets``) — that Bob QUOTES the addressed message only when a
third participant is present. Behaviour is pinned as a user would see it, never via
Bob's internals.

The scenarios are synchronous (pytest-bdd), so each async turn runs via ``asyncio.run``
inside its When step — no event loop is active around it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.fake_gateway import (
    _OWNER_MESSAGE_ID,
    run_group_turn,
    run_turn,
)

if TYPE_CHECKING:
    from tests.acceptance.conftest import ScenarioContext

# The scripted Tier-1 answer Bob composes when he replies — the observable reply that
# reaches the participant through the gateway (its quote, or absence, is the contract).
_SCRIPTED_REPLY = "Зонды — моя стихия, давай по делу…"

scenarios("../features/reply_to.feature")


@given("Боб запущен и слушает свой топик")
def bob_is_running(scenario_context: ScenarioContext) -> None:
    """Readiness — the fresh temp db + soul are set up by the fixture; the turn boots
    the graph in the When step, so this step just asserts a clean slate."""
    assert not scenario_context.gateway.replied


@when(
    parsers.parse(
        'в общем треде уже говорил другой участник и затем к Бобу обращаются: "{text}"'
    )
)
def multiparty_addresses_bob(scenario_context: ScenarioContext, text: str) -> None:
    """Drive a multi-party turn: a third voice spoke first, then the owner addresses Bob."""
    scenario_context.gateway = asyncio.run(
        run_group_turn(scenario_context.tmp_path, text=text, reply=_SCRIPTED_REPLY)
    )


@when(parsers.parse('наедине к Бобу обращаются: "{text}"'))
def one_to_one_addresses_bob(scenario_context: ScenarioContext, text: str) -> None:
    """Drive the SAME direct address in a private 1:1 thread (no third participant)."""
    scenario_context.gateway = asyncio.run(
        run_turn(scenario_context.tmp_path, text=text, reply=_SCRIPTED_REPLY)
    )


@then("Боб отправляет ответную реплику в этот чат")
def bob_replies(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.replied, "Боб промолчал на прямое обращение"


@then("реплика цитирует именно то сообщение, на которое отвечает")
def reply_quotes_the_addressed_message(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.last_reply_quoted == _OWNER_MESSAGE_ID


@then("реплика не содержит цитаты — уходит в топик как раньше")
def reply_has_no_quote(scenario_context: ScenarioContext) -> None:
    assert scenario_context.gateway.last_reply_quoted is None
