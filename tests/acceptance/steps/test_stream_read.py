# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the holistic stream-read scenarios (BOB-072).

Binds ``stream_read.feature`` to the real-dispatcher harness (real ChatDispatcher + focus
predicate + queue-level coalesce, a scripted fake batch reader supplying each ambient message's
semantic verdict). The scenarios pin Bob's OBSERVABLE, un-scripted choice through the boundary:

* a burst is read holistically — a word for the meaningful question, a like for the good joke,
  silence for the chatter and «ок» — and EVERY message stays in memory (INV-S2);
* a direct address in the burst is always answered (INV-1);
* pure cross-talk earns silence but is still remembered;
* a superseded reformulation is never answered (INV-S3) yet still persisted (INV-S2).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.stream_read_harness import (
    BurstMessage,
    StreamObservations,
    burst_chatter_with_one_question_and_a_joke,
    burst_cross_talk_between_two,
    burst_with_a_direct_address,
    burst_with_a_superseded_reformulation,
    drive_stream,
)

scenarios("../features/stream_read.feature")

# The message_ids the harness bursts use for the meaningful message / joke / direct address.
_QUESTION_ID = 3
_JOKE_ID = 4
_ADDRESS_ID = 2
_FRESH_QUESTION_ID = 3
_SUPERSEDED_ID = 1


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the stream-read scenario's steps share."""

    specs: list[BurstMessage] = field(default_factory=list)
    stale_coalesce: bool = False
    observations: StreamObservations = field(default_factory=StreamObservations)


@given(
    "осевшая пачка болтовни с одним осмысленным вопросом и одной удачной шуткой",
    target_fixture="stream_ctx",
)
def burst_chatter() -> _Ctx:
    return _Ctx(specs=burst_chatter_with_one_question_and_a_joke())


@given(
    "пачка болтовни, в которую вклинилось прямое обращение к Бобу",
    target_fixture="stream_ctx",
)
def burst_with_address() -> _Ctx:
    return _Ctx(specs=burst_with_a_direct_address())


@given(
    "пачка, где двое переговариваются между собой, не про Боба",
    target_fixture="stream_ctx",
)
def burst_cross_talk() -> _Ctx:
    return _Ctx(specs=burst_cross_talk_between_two())


@given(
    "пачка, где тот же участник тут же переформулировал свою реплику",
    target_fixture="stream_ctx",
)
def burst_superseded() -> _Ctx:
    return _Ctx(specs=burst_with_a_superseded_reformulation(), stale_coalesce=True)


@when("Боб читает поток целиком")
def read_the_stream(stream_ctx: _Ctx) -> None:
    stream_ctx.observations = asyncio.run(
        drive_stream(specs=stream_ctx.specs, stale_coalesce=stream_ctx.stale_coalesce)
    )


@when("Боб читает поток целиком со свёрткой протухших")
def read_the_stream_with_coalesce(stream_ctx: _Ctx) -> None:
    stream_ctx.observations = asyncio.run(
        drive_stream(specs=stream_ctx.specs, stale_coalesce=True)
    )


@then("Боб отвечает словами на осмысленный вопрос")
def answers_the_question(stream_ctx: _Ctx) -> None:
    assert _QUESTION_ID in stream_ctx.observations.replies, (
        "осмысленный вопрос остался без ответа"
    )


@then("Боб лайкает удачную шутку")
def likes_the_joke(stream_ctx: _Ctx) -> None:
    assert _JOKE_ID in stream_ctx.observations.likes, "удачная шутка не лайкнута"


@then("Боб молчит на пустую болтовню и «ок»")
def silent_on_chatter(stream_ctx: _Ctx) -> None:
    silent = set(stream_ctx.observations.silent)
    # The weather chatter (1, 2) and the empty «ок» (5) earned silence — not a word, not a like.
    assert {1, 2, 5} <= silent, f"ожидалось молчание на 1,2,5; молча: {sorted(silent)}"
    # And Bob did not over-react: he answered exactly the one question and liked exactly the joke.
    assert stream_ctx.observations.replies == [_QUESTION_ID]
    assert stream_ctx.observations.likes == [_JOKE_ID]


@then("Боб отвечает на прямое обращение")
def answers_the_address(stream_ctx: _Ctx) -> None:
    assert _ADDRESS_ID in stream_ctx.observations.replies, (
        "прямое обращение осталось без ответа (INV-1)"
    )


@then("Боб не отвечает и не лайкает ни одной реплики")
def stays_fully_silent(stream_ctx: _Ctx) -> None:
    assert stream_ctx.observations.replies == [], "Боб влез в кросс-ток, хотя не должен"
    assert stream_ctx.observations.likes == [], "Боб лайкнул кросс-ток, хотя не должен"


@then("Боб не отвечает на протухшую реплику")
def no_reply_to_stale(stream_ctx: _Ctx) -> None:
    assert _SUPERSEDED_ID not in stream_ctx.observations.replies, (
        "Боб ответил на протухшую (перекрытую) реплику"
    )


@then("Боб отвечает на свежий вопрос от другого участника")
def answers_the_fresh_question(stream_ctx: _Ctx) -> None:
    assert _FRESH_QUESTION_ID in stream_ctx.observations.replies, (
        "свежий вопрос от другого участника остался без ответа"
    )


@then("все сообщения пачки остаются в памяти")
def all_persisted(stream_ctx: _Ctx) -> None:
    expected = sorted(spec.message_id for spec in stream_ctx.specs)
    assert sorted(stream_ctx.observations.persisted) == expected, (
        f"персист не для всех: {sorted(stream_ctx.observations.persisted)} != {expected}"
    )
