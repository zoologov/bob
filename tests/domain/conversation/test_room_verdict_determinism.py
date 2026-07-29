# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Exhaustive determinism table for the reflective verdict core (BOB-066 Срез 2.2).

Complements the per-branch unit tests with the FULL cartesian mapping the gate depends
on: every :class:`ReflectiveIntent` x the salience band (above / below the floor) →
exactly one :class:`VerdictKind`. Locks the pure core so a NEW intent cannot silently
default to REPLY and a threshold flip cannot survive mutation. Also pins the edge the
wire normally guards (a negative salience in the reading → IGNORE) and the emoji
passthrough (a REACT with no chosen emoji leaves ``emoji=None`` for the gate to fill).
"""

from __future__ import annotations

import pytest

from bob.conversation.room_reading import ReflectiveIntent, RoomMood, RoomReading
from bob.conversation.room_verdict import (
    SALIENCE_THRESHOLD,
    VerdictKind,
    decide_from_reading,
)

# A salience clearly ABOVE the engage floor and one clearly BELOW it.
_ABOVE = 0.9
_BELOW = 0.05


def _reading(
    *,
    intent: ReflectiveIntent,
    salience: float,
    emoji: str | None = None,
    wants_web: bool = False,
    addressee_id: int | None = None,
) -> RoomReading:
    return RoomReading(
        situation="s",
        pairings=(),
        room_mood=RoomMood.NEUTRAL,
        intent=intent,
        addressee_id=addressee_id,
        salience=salience,
        emoji=emoji,
        wants_web=wants_web,
        reason="r",
    )


# --- the full intent x salience-band → verdict table --------------------------

# Above the floor every intent maps deterministically; below the floor the salience gate
# fires FIRST, so the outcome is IGNORE whatever the intent (Bob doesn't barge into a room
# he doesn't matter to this turn).
_ABOVE_FLOOR: dict[ReflectiveIntent, VerdictKind] = {
    ReflectiveIntent.REPLY: VerdictKind.REPLY,
    ReflectiveIntent.INITIATE: VerdictKind.REPLY,  # a reactive INITIATE → barge-in reply
    ReflectiveIntent.REACT: VerdictKind.REACT,
    ReflectiveIntent.IGNORE: VerdictKind.IGNORE,
    ReflectiveIntent.SELF_CHECK: VerdictKind.IGNORE,  # inward → no outward act
}


@pytest.mark.parametrize("intent", list(ReflectiveIntent))
def test_above_the_floor_every_intent_maps_to_its_verdict(
    intent: ReflectiveIntent,
) -> None:
    verdict = decide_from_reading(
        _reading(intent=intent, salience=_ABOVE, emoji="🔥")
    )
    assert verdict.kind is _ABOVE_FLOOR[intent]


@pytest.mark.parametrize("intent", list(ReflectiveIntent))
def test_below_the_floor_every_intent_is_silenced(intent: ReflectiveIntent) -> None:
    verdict = decide_from_reading(
        _reading(intent=intent, salience=_BELOW, emoji="🔥")
    )
    assert verdict.kind is VerdictKind.IGNORE


def test_the_table_covers_every_declared_intent() -> None:
    # Guards the mapping stays TOTAL: a newly added ReflectiveIntent must be classified
    # here (and in the core) rather than falling through to an accidental REPLY.
    assert set(_ABOVE_FLOOR) == set(ReflectiveIntent)


# --- boundary + edge cases the gate leans on ---------------------------------


def test_salience_exactly_at_the_floor_engages() -> None:
    # `<` is strict — a read AT the bar still engages.
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REPLY, salience=SALIENCE_THRESHOLD)
    )
    assert verdict.kind is VerdictKind.REPLY


def test_a_negative_salience_reading_is_silenced() -> None:
    # The wire clamps salience to [0, 1], but the core is defensive: a below-zero salience
    # is far under the floor → IGNORE (never read as its magnitude — the dev's regex fix).
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REPLY, salience=-0.4)
    )
    assert verdict.kind is VerdictKind.IGNORE


def test_a_react_without_a_chosen_emoji_passes_through_as_none() -> None:
    # The core carries the reading's emoji verbatim (here None); the gate substitutes a
    # mood emoji downstream — the core does not invent one.
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REACT, emoji=None, salience=_ABOVE)
    )
    assert verdict.kind is VerdictKind.REACT
    assert verdict.emoji is None


def test_wants_web_rides_only_the_reply_verdict() -> None:
    # wants_web forces the verify pass ONLY on a REPLY; a REACT that (nonsensically) set it
    # never forces web (the flag rides the reply verdict alone).
    reply = decide_from_reading(
        _reading(intent=ReflectiveIntent.REPLY, salience=_ABOVE, wants_web=True)
    )
    react = decide_from_reading(
        _reading(
            intent=ReflectiveIntent.REACT, salience=_ABOVE, emoji="👍", wants_web=True
        )
    )
    assert reply.force_web is True
    assert react.force_web is False


def test_a_silenced_read_carries_no_addressee_or_web() -> None:
    # An IGNORE verdict is the inert value: no addressee, no forced web, no emoji.
    verdict = decide_from_reading(
        _reading(intent=ReflectiveIntent.REPLY, salience=_BELOW, addressee_id=6)
    )
    assert verdict.addressee_id is None
    assert verdict.force_web is False
    assert verdict.emoji is None
