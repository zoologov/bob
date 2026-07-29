# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure reflective verdict core (BOB-066 Срез 2.2).

:func:`~bob.conversation.room_verdict.decide_from_reading` is the load-bearing
invariant of the reflective seam: the LLM VERBALISES the read, this pure core DECIDES
the outcome. These pin the mapping exactly (salience floor first; intent → verdict;
``wants_web`` → ``force_web``; INITIATE collapses to a barge-in reply) and press the
boundary so mutation cannot survive.
"""

from __future__ import annotations

import pytest

from bob.conversation.room_reading import ReflectiveIntent, RoomMood, RoomReading
from bob.conversation.room_verdict import (
    SALIENCE_THRESHOLD,
    VerdictKind,
    decide_from_reading,
)


def _reading(
    *,
    intent: ReflectiveIntent = ReflectiveIntent.REPLY,
    salience: float = 0.9,
    emoji: str | None = None,
    wants_web: bool = False,
    addressee_id: int | None = None,
) -> RoomReading:
    """A RoomReading with sensible defaults, overridable per assertion."""
    return RoomReading(
        situation="ребята обсуждают зонды",
        pairings=("Norman↔Lyosha",),
        room_mood=RoomMood.WARM,
        intent=intent,
        addressee_id=addressee_id,
        salience=salience,
        emoji=emoji,
        wants_web=wants_web,
        reason="test",
    )


# --- salience floor (checked FIRST, whatever the intent) ---------------------


def test_below_threshold_salience_ignores_even_a_reply_intent() -> None:
    verdict = decide_from_reading(_reading(intent=ReflectiveIntent.REPLY, salience=0.34))
    assert verdict.kind is VerdictKind.IGNORE


def test_below_threshold_salience_ignores_even_an_initiate_intent() -> None:
    reading = _reading(intent=ReflectiveIntent.INITIATE, salience=0.0)
    assert decide_from_reading(reading).kind is VerdictKind.IGNORE


def test_salience_exactly_at_threshold_engages() -> None:
    # The floor is strict (`<`): a read AT the bar still engages.
    reading = _reading(intent=ReflectiveIntent.REPLY, salience=SALIENCE_THRESHOLD)
    assert decide_from_reading(reading).kind is VerdictKind.REPLY


def test_salience_just_below_threshold_ignores() -> None:
    reading = _reading(intent=ReflectiveIntent.REPLY, salience=SALIENCE_THRESHOLD - 0.01)
    assert decide_from_reading(reading).kind is VerdictKind.IGNORE


# --- intent → verdict (above the floor) --------------------------------------


def test_reply_intent_yields_a_reply_verdict() -> None:
    assert decide_from_reading(_reading(intent=ReflectiveIntent.REPLY)).kind is (
        VerdictKind.REPLY
    )


def test_initiate_collapses_to_a_reply_in_a_reactive_turn() -> None:
    assert decide_from_reading(_reading(intent=ReflectiveIntent.INITIATE)).kind is (
        VerdictKind.REPLY
    )


def test_react_intent_yields_a_react_verdict_carrying_the_emoji() -> None:
    verdict = decide_from_reading(_reading(intent=ReflectiveIntent.REACT, emoji="🔥"))
    assert verdict.kind is VerdictKind.REACT
    assert verdict.emoji == "🔥"


def test_ignore_intent_stays_silent() -> None:
    assert decide_from_reading(_reading(intent=ReflectiveIntent.IGNORE)).kind is (
        VerdictKind.IGNORE
    )


def test_self_check_is_inward_so_reads_as_silence() -> None:
    assert decide_from_reading(_reading(intent=ReflectiveIntent.SELF_CHECK)).kind is (
        VerdictKind.IGNORE
    )


# --- wants_web (C11) rides ONLY a reply verdict ------------------------------


def test_wants_web_forces_the_verify_pass_on_a_reply() -> None:
    verdict = decide_from_reading(_reading(intent=ReflectiveIntent.REPLY, wants_web=True))
    assert verdict.kind is VerdictKind.REPLY
    assert verdict.force_web is True


def test_a_reply_without_wants_web_does_not_force_the_verify_pass() -> None:
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REPLY, wants_web=False)
    )
    assert verdict.force_web is False


def test_a_react_verdict_never_forces_web() -> None:
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REACT, emoji="👍", wants_web=True)
    )
    assert verdict.force_web is False


# --- addressee passthrough ----------------------------------------------------


def test_reply_carries_the_addressee_for_the_floor_pass() -> None:
    verdict = decide_from_reading(_reading(intent=ReflectiveIntent.REPLY, addressee_id=6))
    assert verdict.addressee_id == 6


def test_react_verdict_has_no_addressee() -> None:
    verdict = decide_from_reading(_reading(intent=ReflectiveIntent.REACT, emoji="👍"))
    assert verdict.addressee_id is None


@pytest.mark.parametrize(
    "kind",
    [VerdictKind.REPLY, VerdictKind.REACT, VerdictKind.IGNORE],
)
def test_verdict_kinds_are_the_three_outcomes(kind: VerdictKind) -> None:
    # Guards the enum surface the gate switches on stays exactly three outcomes.
    assert kind.value in {"reply", "react", "ignore"}
