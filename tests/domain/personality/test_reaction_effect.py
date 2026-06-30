# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure reaction-effect kernel (BOB-050 .2).

A reaction's MEANING is turned into bounded nudges to Bob's mood and his relationship
with the reactor — a warm one lifts (displacing accumulated low via the BOB-033
contagion path), a cold one only dips, and every move stays inside the band.
"""

from __future__ import annotations

from bob.domain.personality.mood import Mood, MoodDelta
from bob.domain.personality.reaction_effect import (
    apply_reaction_to_mood,
    nudge_relationship_warmth,
)
from bob.domain.personality.reaction_meaning import ReactionMeaning
from bob.domain.personality.relationship import Relationship


def _meaning(*, valence: float, warmth_nudge: float) -> ReactionMeaning:
    return ReactionMeaning(
        interpretation="x",
        mood_delta=MoodDelta(valence=valence, social=0.05 if valence > 0 else 0.0),
        warmth_nudge=warmth_nudge,
        worth_acknowledging=valence > 0,
    )


def test_warm_reaction_lifts_mood_from_a_dip() -> None:
    low = Mood(valence=-0.4)
    baseline = Mood(valence=0.5)

    lifted = apply_reaction_to_mood(
        low, _meaning(valence=0.2, warmth_nudge=0.1), baseline=baseline, lift_rate=0.3
    )

    # Pulled up toward baseline (displace-the-low) AND the positive delta lands.
    assert lifted.valence > low.valence
    assert lifted.social > low.social  # the social lift is applied


def test_cold_reaction_dips_without_a_baseline_pull() -> None:
    mood = Mood(valence=0.3)
    baseline = Mood(valence=0.5)

    dipped = apply_reaction_to_mood(
        mood, _meaning(valence=-0.15, warmth_nudge=-0.08), baseline=baseline, lift_rate=0.3
    )

    # A negative reaction skips the toward-baseline lift and only applies its dip.
    assert dipped.valence < mood.valence


def test_mood_effect_stays_clamped_in_band() -> None:
    near_top = Mood(valence=0.95)
    lifted = apply_reaction_to_mood(
        near_top, _meaning(valence=0.25, warmth_nudge=0.12),
        baseline=Mood(valence=1.0), lift_rate=0.4,
    )
    assert -1.0 <= lifted.valence <= 1.0


def test_warmth_nudge_moves_only_warmth() -> None:
    rel = Relationship(sender_id=7, trust=0.2, respect=0.1, warmth=0.0, compatibility=0.3)

    warmer = nudge_relationship_warmth(rel, _meaning(valence=0.2, warmth_nudge=0.1))

    assert warmer.warmth > rel.warmth
    assert warmer.trust == rel.trust
    assert warmer.respect == rel.respect
    assert warmer.compatibility == rel.compatibility


def test_warmth_nudge_clamped_to_axis_bounds() -> None:
    rel = Relationship(sender_id=7, warmth=0.95)
    warmer = nudge_relationship_warmth(rel, _meaning(valence=0.2, warmth_nudge=0.12))
    assert -1.0 <= warmer.warmth <= 1.0


def test_dismissive_reaction_cools_warmth() -> None:
    rel = Relationship(sender_id=7, warmth=0.2)
    cooler = nudge_relationship_warmth(rel, _meaning(valence=-0.15, warmth_nudge=-0.08))
    assert cooler.warmth < rel.warmth
