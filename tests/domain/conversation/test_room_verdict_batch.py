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


def test_initiate_message_collapses_to_a_reply_in_the_batch() -> None:
    # 🔴 The full intent map must hold per-message: a reactive INITIATE (someone said
    # something Bob wants to pick up) is a barge-in REPLY, exactly as the single path decides.
    (verdict,) = decide_batch([
        _reading(intent=ReflectiveIntent.INITIATE, salience=0.8),
    ])
    assert verdict.kind is VerdictKind.REPLY


def test_self_check_message_stays_silent_in_the_batch() -> None:
    # SELF_CHECK is inward — no outward act in a reactive turn — so it reads as silence even
    # above the salience floor (the batch must not turn an inward read into a reply/react).
    (verdict,) = decide_batch([
        _reading(intent=ReflectiveIntent.SELF_CHECK, salience=0.9),
    ])
    assert verdict.kind is VerdictKind.IGNORE


def test_message_at_the_salience_threshold_still_engages() -> None:
    # 🔴 Boundary (`<` is strict): a read AT the floor is NOT silenced — it engages. Pins the
    # off-by-one at the «стоит ли влезть» bar in the batch projection.
    (verdict,) = decide_batch([
        _reading(intent=ReflectiveIntent.REPLY, salience=SALIENCE_THRESHOLD),
    ])
    assert verdict.kind is VerdictKind.REPLY


def test_mixed_batch_projects_reply_on_one_and_silence_on_the_rest_in_order() -> None:
    # 🔴 INV-S2 shape at the policy layer: a burst where only ONE message is worth a word
    # projects a REPLY for it and IGNORE for the others, each in arrival order — the plan is a
    # faithful per-message projection (never a single collapsed verdict for the whole burst).
    readings = [
        _reading(intent=ReflectiveIntent.IGNORE, salience=0.9),
        _reading(intent=ReflectiveIntent.REPLY, salience=0.9, addressee_id=42),
        _reading(intent=ReflectiveIntent.IGNORE, salience=0.9),
    ]
    plan = decide_batch(readings)
    assert [verdict.kind for verdict in plan] == [
        VerdictKind.IGNORE,
        VerdictKind.REPLY,
        VerdictKind.IGNORE,
    ]
    # The single meaningful message keeps its addressee (reply-to routing survives the batch).
    assert plan[1].addressee_id == 42
