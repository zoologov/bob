# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SOUL — the in-memory snapshot of Bob's persisted soul (no I/O)."""

from __future__ import annotations

import pytest

from bob.personality.mood import Mood, MoodDelta
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine, Verdict


def _soul() -> SOUL:
    return SOUL(
        identity="I am Bob — yes, that Bob, from the book.",
        mood=Mood(valence=0.3, arousal=-0.1),
        mood_baseline=Mood(valence=0.1),
        taste=TasteEngine(axes=(TasteAxis(name="coffee", value=0.9, conviction=0.9),)),
        phantom_prefs=("coffee", "sunsets", "the smell of old books"),
    )


def test_soul_holds_its_components() -> None:
    # Arrange / Act
    soul = _soul()

    # Assert
    assert "Bob" in soul.identity
    assert soul.mood.valence == pytest.approx(0.3)
    assert soul.mood_baseline.valence == pytest.approx(0.1)
    assert soul.phantom_prefs == ("coffee", "sunsets", "the smell of old books")


def test_soul_taste_is_usable_for_scoring() -> None:
    # Arrange
    soul = _soul()

    # Act
    verdict = soul.taste.score("coffee")

    # Assert: SOUL exposes the live taste engine for verdicts.
    assert verdict is Verdict.LOVE


def test_soul_is_immutable() -> None:
    # Arrange
    soul = _soul()

    # Act / Assert: the soul snapshot is a frozen value object.
    with pytest.raises(AttributeError):
        soul.identity = "someone else"  # type: ignore[misc]


def test_soul_with_mood_returns_updated_snapshot() -> None:
    # Arrange
    soul = _soul()
    new_mood = Mood(valence=-0.5)

    # Act: swap mood (e.g. after UpdateMoodFromText) without mutating the soul.
    updated = soul.with_mood(new_mood)

    # Assert: a new snapshot carries the new mood; the rest is preserved.
    assert updated.mood.valence == pytest.approx(-0.5)
    assert updated.identity == soul.identity
    assert updated.phantom_prefs == soul.phantom_prefs
    assert soul.mood.valence == pytest.approx(0.3)
    assert updated is not soul


def test_soul_defaults_phantom_prefs_to_empty() -> None:
    # Arrange / Act
    soul = SOUL(identity="x", mood=Mood(), mood_baseline=Mood(), taste=TasteEngine())

    # Assert: optional collections default to a safe empty, never a shared mutable.
    assert soul.phantom_prefs == ()


def test_soul_defaults_experience_count_to_zero() -> None:
    # Arrange / Act
    soul = SOUL(identity="x", mood=Mood(), mood_baseline=Mood(), taste=TasteEngine())

    # Assert: a fresh soul has experienced no self-evolution yet.
    assert soul.experience_count == 0


def test_soul_with_taste_swaps_axes_and_bumps_experience() -> None:
    # Arrange
    soul = _soul()
    evolved_axes = (TasteAxis(name="coffee", value=0.95, conviction=0.92),)

    # Act: self-evolution applied a reinforced axis set.
    updated = soul.with_taste(evolved_axes)

    # Assert: the live taste engine carries the new axes and experience ticks up.
    assert updated.taste.axes == evolved_axes
    assert updated.experience_count == soul.experience_count + 1
    assert updated.identity == soul.identity
    assert updated is not soul
    # Original is untouched (immutable).
    assert soul.experience_count == 0


def test_soul_with_phantoms_swaps_membership_and_bumps_experience() -> None:
    # Arrange
    soul = _soul()
    evolved = ("coffee", "sunsets", "night trains")

    # Act: a phantom-evolution step swapped in a new membership (a self-evolution step).
    updated = soul.with_phantoms(evolved)

    # Assert: the new phantom set is carried; experience ticks up like with_taste.
    assert updated.phantom_prefs == evolved
    assert updated.experience_count == soul.experience_count + 1
    assert updated.identity == soul.identity
    assert updated.mood == soul.mood
    assert updated is not soul
    # Original is untouched (immutable).
    assert soul.phantom_prefs == ("coffee", "sunsets", "the smell of old books")
    assert soul.experience_count == 0


def test_soul_with_baseline_shifts_resting_mood() -> None:
    # Arrange
    soul = _soul()
    delta = MoodDelta(valence=0.1)

    # Act: a small, durable shift of the resting set-point.
    updated = soul.with_baseline(delta)

    # Assert: baseline moved by the delta, clamped; mood/identity preserved.
    assert updated.mood_baseline.valence == pytest.approx(0.2)
    assert updated.mood == soul.mood
    assert updated is not soul
    assert soul.mood_baseline.valence == pytest.approx(0.1)
