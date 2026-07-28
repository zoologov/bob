# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the floor-по-говорящему acceptance scenarios (BOB-066 .1).

Binds the Gherkin of ``floor_by_speaker.feature`` to :mod:`tests.acceptance.floor_harness`.
Владимир opens a live thread with Bob by addressing him directly (Bob answers, so Владимир
joins Bob's floor participants); the scenario then drives ONE more unlabeled turn and asserts
Bob's observable behaviour through the gateway: he CONTINUES with a recognised participant,
and does NOT wrongly take a stranger's unlabeled reply.

The whole turn sequence is driven at the When step (one booted graph, so the conversation
floor carries in-process), and the Then asserts on the recorded per-turn replies. The
scenarios are synchronous (pytest-bdd), so the async run is driven via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.floor_harness import (
    OUTSIDER,
    PARTICIPANT,
    Speaker,
    run_floor_turns,
)

if TYPE_CHECKING:
    from pathlib import Path

# The direct address Владимир opens the thread with (a name-address → DIRECTED_TO_BOB, so
# Bob answers and Владимир joins the floor participants).
_OPENER = "Bob, расскажи подробно про зонды"

scenarios("../features/floor_by_speaker.feature")


@dataclass(slots=True)
class FloorContext:
    """The slate the floor scenario's steps share: the temp db root, the queued turns,
    and the per-turn replied flags once the sequence is driven."""

    tmp_path: Path
    turns: list[tuple[Speaker, str]] = field(default_factory=list)
    replied: list[bool] = field(default_factory=list)


@pytest.fixture
def floor_context(tmp_path: Path) -> FloorContext:
    """A fresh, isolated floor context (temp db + soul) per acceptance scenario."""
    return FloorContext(tmp_path=tmp_path)


@given("Боб запущен и слушает свой топик")
def bob_is_running(floor_context: FloorContext) -> None:
    """A clean slate — no turns queued and nothing driven yet."""
    assert not floor_context.turns
    assert not floor_context.replied


@given("Владимир напрямую обратился к Бобу и Боб ответил")
def vladimir_opens_the_thread(floor_context: FloorContext) -> None:
    """Queue the opening direct-address turn; the reply is asserted once driven."""
    floor_context.turns.append((PARTICIPANT, _OPENER))


@when(parsers.parse('Владимир пишет в нить безметочную реплику "{text}"'))
def vladimir_writes_unlabeled(floor_context: FloorContext, text: str) -> None:
    """Queue Владимир's unlabeled follow-up and drive the whole sequence."""
    floor_context.turns.append((PARTICIPANT, text))
    _drive(floor_context)


@when(parsers.parse('посторонний Норман пишет в нить безметочную реплику "{text}"'))
def norman_writes_unlabeled(floor_context: FloorContext, text: str) -> None:
    """Queue the outsider's unlabeled reply and drive the whole sequence."""
    floor_context.turns.append((OUTSIDER, text))
    _drive(floor_context)


@then("Боб отвечает на эту реплику")
def bob_replies_to_the_last_turn(floor_context: FloorContext) -> None:
    assert floor_context.replied[0], "Боб не ответил на прямое обращение (предыстория)"
    assert floor_context.replied[-1], "Боб промолчал на реплику участника живой нити"


@then("Боб не отвечает на эту реплику")
def bob_stays_silent_on_the_last_turn(floor_context: FloorContext) -> None:
    assert floor_context.replied[0], "Боб не ответил на прямое обращение (предыстория)"
    assert not floor_context.replied[-1], "Боб ошибочно перехватил реплику постороннего"


def _drive(floor_context: FloorContext) -> None:
    floor_context.replied = asyncio.run(
        run_floor_turns(floor_context.tmp_path, floor_context.turns)
    )
