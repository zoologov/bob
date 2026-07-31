# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``decide_batch`` — the pure per-message projection of a batch read (BOB-072).

The holistic stream-read VERBALISES a per-message reading for a whole ambient batch; this
pure core PROJECTS each reading to its verdict with the SAME deterministic policy as
``decide_from_reading`` (salience floor first, then intent map), in arrival order. The
mutation-tested policy core of the batch seam — no I/O, no RNG.
"""

from __future__ import annotations

from bob.conversation.room_reading import (
    ReflectiveIntent,
    RoomMood,
    RoomReading,
)
from bob.conversation.room_verdict import (
    SALIENCE_THRESHOLD,
    VerdictKind,
    decide_batch,
)


def _reading(
    *,
    intent: ReflectiveIntent,
    salience: float,
    emoji: str | None = None,
    wants_web: bool = False,
    addressee_id: int | None = None,
) -> RoomReading:
    """Build a per-message reading with only the fields the verdict core weighs."""
    return RoomReading(
        situation="",
        pairings=(),
        room_mood=RoomMood.NEUTRAL,
        intent=intent,
        addressee_id=addressee_id,
        salience=salience,
        emoji=emoji,
        wants_web=wants_web,
        reason="",
    )


def test_empty_batch_yields_empty_plan() -> None:
    assert decide_batch(()) == []


def test_projects_each_message_in_order() -> None:
    readings = [
        _reading(intent=ReflectiveIntent.REPLY, salience=0.9),
        _reading(intent=ReflectiveIntent.IGNORE, salience=0.9),
        _reading(intent=ReflectiveIntent.REACT, salience=0.9, emoji="🔥"),
    ]
    plan = decide_batch(readings)
    assert [verdict.kind for verdict in plan] == [
        VerdictKind.REPLY,
        VerdictKind.IGNORE,
        VerdictKind.REACT,
    ]


def test_low_salience_message_stays_silent_whatever_the_intent() -> None:
    readings = [
        _reading(intent=ReflectiveIntent.REPLY, salience=SALIENCE_THRESHOLD - 0.01),
        _reading(intent=ReflectiveIntent.REACT, salience=0.0, emoji="🔥"),
    ]
    plan = decide_batch(readings)
    assert all(verdict.kind is VerdictKind.IGNORE for verdict in plan)


def test_react_message_carries_its_emoji() -> None:
    (verdict,) = decide_batch([
        _reading(intent=ReflectiveIntent.REACT, salience=0.8, emoji="🔥"),
    ])
    assert verdict.kind is VerdictKind.REACT
    assert verdict.emoji == "🔥"


def test_reply_message_carries_web_and_addressee() -> None:
    (verdict,) = decide_batch([
        _reading(
            intent=ReflectiveIntent.REPLY,
            salience=0.8,
            wants_web=True,
            addressee_id=42,
        ),
    ])
    assert verdict.kind is VerdictKind.REPLY
    assert verdict.force_web is True
    assert verdict.addressee_id == 42


def test_plan_length_matches_the_batch() -> None:
    readings = [_reading(intent=ReflectiveIntent.IGNORE, salience=0.5)] * 4
    assert len(decide_batch(readings)) == 4
