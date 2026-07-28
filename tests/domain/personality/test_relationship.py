# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Relationship — Bob's per-person relationship quality (BOB-014).

A pure, bounded value object (trust/respect/warmth/compatibility ∈ [-1, 1]) plus
:func:`apply_interaction` — a deterministic step that warms/cools the relationship
from one turn's (stance, mood, sentiment) with small bounded deltas and a gentle
drift toward neutral 0 so it never runs away. Every axis stays clamped to [-1, 1].
"""

from __future__ import annotations

import pytest

from bob.personality.mood import Mood
from bob.personality.negotiation import Stance
from bob.social.relationship import (
    Relationship,
    RelationshipDeltas,
    apply_interaction,
    compromise_bias,
)

_SENDER = 7777

_GOOD_MOOD = Mood(valence=0.6, arousal=0.2)
_BAD_MOOD = Mood(valence=-0.6, arousal=0.1)
_NEUTRAL_MOOD = Mood()


def test_defaults_to_neutral() -> None:
    rel = Relationship(sender_id=_SENDER)

    assert rel.trust == 0.0
    assert rel.respect == 0.0
    assert rel.warmth == 0.0
    assert rel.compatibility == 0.0


@pytest.mark.parametrize("axis", ["trust", "respect", "warmth", "compatibility"])
def test_rejects_out_of_bounds_axis(axis: str) -> None:
    with pytest.raises(ValueError, match=axis):
        Relationship(sender_id=_SENDER, **{axis: 1.5})


def test_positive_sentiment_and_mood_warm_the_relationship() -> None:
    rel = Relationship(sender_id=_SENDER)

    after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_GOOD_MOOD, sentiment=0.6
    )

    assert after.warmth > rel.warmth
    assert after.trust > rel.trust
    assert after.sender_id == _SENDER


def test_negative_sentiment_and_mood_cool_the_relationship() -> None:
    rel = Relationship(sender_id=_SENDER, warmth=0.3, trust=0.3)

    after = apply_interaction(
        rel, stance=Stance.PROPOSE_ALTERNATIVE, mood=_BAD_MOOD, sentiment=-0.6
    )

    assert after.warmth < rel.warmth
    assert after.trust < rel.trust


def test_concede_warms_differently_than_propose_alternative() -> None:
    rel = Relationship(sender_id=_SENDER)

    conceded = apply_interaction(
        rel, stance=Stance.CONCEDE, mood=_NEUTRAL_MOOD, sentiment=0.0
    )
    pushed = apply_interaction(
        rel, stance=Stance.PROPOSE_ALTERNATIVE, mood=_NEUTRAL_MOOD, sentiment=0.0
    )

    # Conceding (yielding to the person) warms more than holding ground does.
    assert conceded.warmth > pushed.warmth


def test_deltas_are_small_and_bounded() -> None:
    rel = Relationship(sender_id=_SENDER)

    after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_GOOD_MOOD, sentiment=1.0
    )

    # No single interaction moves any axis by more than a small step.
    assert abs(after.warmth - rel.warmth) <= 0.2
    assert abs(after.trust - rel.trust) <= 0.2
    assert abs(after.respect - rel.respect) <= 0.2
    assert abs(after.compatibility - rel.compatibility) <= 0.2


def test_drift_pulls_a_high_relationship_back_toward_neutral() -> None:
    # A warm relationship with a flat, neutral interaction loses a little warmth
    # to the gentle drift toward 0 (it never stays pinned high without upkeep).
    rel = Relationship(sender_id=_SENDER, warmth=0.9, trust=0.9)

    after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_NEUTRAL_MOOD, sentiment=0.0
    )

    assert after.warmth < rel.warmth
    assert after.trust < rel.trust
    assert after.warmth >= 0.0  # drifts toward neutral, never overshoots past it


def test_drift_pulls_a_low_relationship_up_toward_neutral() -> None:
    rel = Relationship(sender_id=_SENDER, warmth=-0.9, trust=-0.9)

    after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_NEUTRAL_MOOD, sentiment=0.0
    )

    assert after.warmth > rel.warmth
    assert after.warmth <= 0.0


def test_always_clamped_to_bounds_under_repeated_warming() -> None:
    rel = Relationship(sender_id=_SENDER)

    for _ in range(200):
        rel = apply_interaction(
            rel, stance=Stance.CONCEDE, mood=_GOOD_MOOD, sentiment=1.0
        )

    for value in (rel.trust, rel.respect, rel.warmth, rel.compatibility):
        assert -1.0 <= value <= 1.0


def test_always_clamped_to_bounds_under_repeated_cooling() -> None:
    rel = Relationship(sender_id=_SENDER)

    for _ in range(200):
        rel = apply_interaction(
            rel, stance=Stance.PROPOSE_ALTERNATIVE, mood=_BAD_MOOD, sentiment=-1.0
        )

    for value in (rel.trust, rel.respect, rel.warmth, rel.compatibility):
        assert -1.0 <= value <= 1.0


def test_compromise_bias_is_higher_for_a_close_relationship() -> None:
    # A close relationship (high warmth + compatibility) makes Bob MORE willing to
    # compromise than a distant one — a positive, larger bias.
    close = Relationship(sender_id=_SENDER, warmth=0.8, compatibility=0.8)
    distant = Relationship(sender_id=_SENDER, warmth=-0.8, compatibility=-0.8)

    assert compromise_bias(close) > compromise_bias(distant)
    assert compromise_bias(close) > 0.0


def test_compromise_bias_is_zero_for_a_neutral_relationship() -> None:
    # A neutral relationship nudges nothing — the negotiation behaves as before.
    assert compromise_bias(Relationship(sender_id=_SENDER)) == 0.0


def test_compromise_bias_for_none_is_zero() -> None:
    # No relationship on record (an unknown sender) → no nudge at all.
    assert compromise_bias(None) == 0.0


def test_custom_deltas_scale_the_step() -> None:
    rel = Relationship(sender_id=_SENDER)
    big = RelationshipDeltas(warmth_step=0.2, trust_step=0.2)

    small_after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_GOOD_MOOD, sentiment=0.5
    )
    big_after = apply_interaction(
        rel, stance=Stance.AGREE, mood=_GOOD_MOOD, sentiment=0.5, deltas=big
    )

    assert big_after.warmth > small_after.warmth
