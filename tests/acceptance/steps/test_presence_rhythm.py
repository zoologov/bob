# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the presence-rhythm acceptance scenarios (BOB-066 .2.3).

Binds the Gherkin of ``presence_rhythm.feature`` to
:mod:`tests.acceptance.presence_harness`: the share-of-voice ceiling throttles an
ambient barge once Bob has hogged the room but NEVER a direct address (INV-1), and
the natural-delay floor keeps a short reply from landing inhumanly fast (INV-9).
The scenarios are synchronous (pytest-bdd), so each async contract is driven via
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.presence_harness import (
    ambient_barge_admitted,
    reply_top_up_delay,
)

scenarios("../features/presence_rhythm.feature")


@dataclass(slots=True)
class RhythmContext:
    """The slate the rhythm scenario's steps share."""

    bob_sent: int = 0
    total_seen: int = 0
    distinct_senders: int = 0
    admitted: bool | None = None
    delay: float | None = None


@pytest.fixture
def rhythm_context() -> RhythmContext:
    return RhythmContext()


@given(
    parsers.parse(
        "Боб наговорил {bob_sent:d} из {total_seen:d} последних реплик "
        "при {distinct:d} активных участниках"
    )
)
def bob_hogged_the_room(
    rhythm_context: RhythmContext, bob_sent: int, total_seen: int, distinct: int
) -> None:
    rhythm_context.bob_sent = bob_sent
    rhythm_context.total_seen = total_seen
    rhythm_context.distinct_senders = distinct


@when(
    parsers.parse(
        "безметочная реплика проходит потолок с базовой вероятностью {base:f} "
        "и жребием {draw:f}"
    )
)
def ambient_passes_ceiling(
    rhythm_context: RhythmContext, base: float, draw: float
) -> None:
    rhythm_context.admitted = asyncio.run(
        ambient_barge_admitted(
            bob_sent=rhythm_context.bob_sent,
            total_seen=rhythm_context.total_seen,
            distinct_senders=rhythm_context.distinct_senders,
            focused=False,
            base_probability=base,
            draw=draw,
        )
    )


@when(
    parsers.parse(
        "прямое обращение проходит потолок с базовой вероятностью {base:f} "
        "и жребием {draw:f}"
    )
)
def focused_passes_ceiling(
    rhythm_context: RhythmContext, base: float, draw: float
) -> None:
    rhythm_context.admitted = asyncio.run(
        ambient_barge_admitted(
            bob_sent=rhythm_context.bob_sent,
            total_seen=rhythm_context.total_seen,
            distinct_senders=rhythm_context.distinct_senders,
            focused=True,
            base_probability=base,
            draw=draw,
        )
    )


@when(parsers.parse('Боб мгновенно сгенерировал короткий ответ "{reply}"'))
def instant_short_reply(rhythm_context: RhythmContext, reply: str) -> None:
    rhythm_context.delay = asyncio.run(reply_top_up_delay(reply=reply))


@then("Боб НЕ влезает в разговор")
def bob_does_not_barge(rhythm_context: RhythmContext) -> None:
    assert rhythm_context.admitted is False, "потолок не притормозил перебор эфира"


@then("Боб влезает в разговор")
def bob_barges(rhythm_context: RhythmContext) -> None:
    assert rhythm_context.admitted is True, "потолок ошибочно задавил прямое обращение"


@then("ответ не уходит быстрее человеческого пола")
def reply_is_floored(rhythm_context: RhythmContext) -> None:
    assert rhythm_context.delay is not None
    assert rhythm_context.delay > 1.0, "короткий ответ ушёл нечеловечески быстро"
