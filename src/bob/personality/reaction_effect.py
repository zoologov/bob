# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Reaction effects — turn a :class:`ReactionMeaning` into bounded state nudges (BOB-050).

The pure kernel of "a reaction changes Bob": given the semantic
:class:`~bob.personality.reaction_meaning.ReactionMeaning`, derive the bounded
moves to his mood and his relationship with the reactor, plus the small durable
"being-received" record the rare-aloud hint (BOB-050 .3) reads. No I/O, no clock —
every move stays inside the BOB-030 band so a single reaction nudges and never swings.

* :func:`apply_reaction_to_mood` — apply the meaning's bounded ``mood_delta`` through
  the same social-contagion path as text (BOB-033): a warm reaction first tugs mood a
  proportional fraction toward Bob's baseline (:meth:`Mood.lift_toward`, displacing
  accumulated low), then the bounded delta lands; a cold/withdrawn reaction only dips.
* :func:`nudge_relationship_warmth` — move Bob's warmth toward the reactor by the
  meaning's bounded ``warmth_nudge`` (someone who resonates → warmer), clamped.
* :class:`NotableReaction` — the light record of a reaction worth being-received,
  recorded only when the meaning is ``worth_acknowledging``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from bob.kernel.relationship import Relationship
    from bob.personality.mood import Mood
    from bob.personality.reaction_meaning import ReactionMeaning

__all__ = [
    "NotableReaction",
    "apply_reaction_to_mood",
    "nudge_relationship_warmth",
]

# Relationship warmth is bounded to [-1, 1] (mirrors the domain axis bounds).
_MIN_AXIS = -1.0
_MAX_AXIS = 1.0


def apply_reaction_to_mood(
    mood: Mood, meaning: ReactionMeaning, *, baseline: Mood, lift_rate: float
) -> Mood:
    """Return ``mood`` nudged by ``meaning`` — bounded, via the BOB-033 contagion path.

    A warm reaction (positive ``mood_delta`` valence) first pulls mood a ``lift_rate``
    fraction of the gap toward ``baseline`` (:meth:`Mood.lift_toward`, the
    "displace-the-low" tug, so being received genuinely charges Bob up), then the
    bounded per-meaning delta lands. A cold/withdrawn reaction skips the lift and only
    applies its small negative delta. Every axis stays clamped to its bounds.
    """
    lifted = mood.lift_toward(baseline, rate=lift_rate) if meaning.mood_delta.valence > 0 else mood
    return lifted.update(meaning.mood_delta)


def nudge_relationship_warmth(rel: Relationship, meaning: ReactionMeaning) -> Relationship:
    """Return ``rel`` with warmth moved by the meaning's bounded ``warmth_nudge`` (clamped).

    A resonant reaction warms Bob toward the reactor; a dismissive one cools him a
    touch. Only the warmth axis moves — a single reaction nudges, it does not re-rate
    trust/respect/compatibility (those accrue through real exchanges, BOB-014).
    """
    warmth = max(_MIN_AXIS, min(_MAX_AXIS, rel.warmth + meaning.warmth_nudge))
    return replace(rel, warmth=warmth)


@dataclass(frozen=True, slots=True)
class NotableReaction:
    """A light, durable record that someone received one of Bob's messages (BOB-050).

    Recorded only when a reaction's meaning is ``worth_acknowledging`` so the rare
    aloud hint (BOB-050 .3) can read the most recent one and let Bob naturally mention
    being received. Per-person (``sender_id`` is the REACTOR), about Bob's own message
    — never owner-private material.
    """

    sender_id: int | None
    reactor_name: str
    emoji: str
    bob_excerpt: str
    interpretation: str
    at: datetime
