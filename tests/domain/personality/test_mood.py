# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure Mood value object (no I/O, deterministic)."""

from __future__ import annotations

import pytest

from bob.domain.personality.mood import Mood, MoodDelta


def test_mood_holds_its_five_axes() -> None:
    # Arrange / Act
    mood = Mood(valence=0.5, arousal=0.2, openness=0.1, social=-0.3, stability=0.4)

    # Assert
    assert mood.valence == pytest.approx(0.5)
    assert mood.arousal == pytest.approx(0.2)
    assert mood.openness == pytest.approx(0.1)
    assert mood.social == pytest.approx(-0.3)
    assert mood.stability == pytest.approx(0.4)


def test_mood_defaults_to_neutral() -> None:
    # Arrange / Act
    mood = Mood()

    # Assert: a fresh mood is the neutral origin of the vector space.
    assert mood.valence == pytest.approx(0.0)
    assert mood.arousal == pytest.approx(0.0)
    assert mood.openness == pytest.approx(0.0)
    assert mood.social == pytest.approx(0.0)
    assert mood.stability == pytest.approx(0.0)


def test_mood_is_immutable() -> None:
    # Arrange
    mood = Mood(valence=0.2)

    # Act / Assert: frozen value object.
    with pytest.raises(AttributeError):
        mood.valence = 0.9  # type: ignore[misc]


@pytest.mark.parametrize("axis", ["valence", "arousal", "openness", "social", "stability"])
def test_mood_rejects_out_of_range_axis(axis: str) -> None:
    # Arrange / Act / Assert: every axis is bounded to [-1, 1].
    with pytest.raises(ValueError, match=axis):
        Mood(**{axis: 1.5})


def test_update_applies_delta_and_returns_new_mood() -> None:
    # Arrange
    mood = Mood(valence=0.1, arousal=0.0)
    delta = MoodDelta(valence=0.3, arousal=-0.2)

    # Act
    updated = mood.update(delta)

    # Assert: a new instance with the delta applied; original untouched.
    assert updated.valence == pytest.approx(0.4)
    assert updated.arousal == pytest.approx(-0.2)
    assert mood.valence == pytest.approx(0.1)
    assert updated is not mood


def test_update_clamps_to_bounds() -> None:
    # Arrange
    mood = Mood(valence=0.9)
    delta = MoodDelta(valence=0.5)

    # Act
    updated = mood.update(delta)

    # Assert: saturates at the +1 ceiling rather than exceeding it.
    assert updated.valence == pytest.approx(1.0)


def test_drift_toward_baseline_moves_a_fraction_of_the_gap() -> None:
    # Arrange: mood far from a calm baseline.
    mood = Mood(valence=1.0, arousal=1.0)
    baseline = Mood(valence=0.0, arousal=0.0)

    # Act: drift halfway toward baseline.
    drifted = mood.drift_toward(baseline, rate=0.5)

    # Assert: each axis moved half the gap to baseline.
    assert drifted.valence == pytest.approx(0.5)
    assert drifted.arousal == pytest.approx(0.5)


def test_drift_toward_baseline_is_idempotent_when_already_there() -> None:
    # Arrange
    baseline = Mood(valence=0.3, social=-0.1)

    # Act
    drifted = baseline.drift_toward(baseline, rate=0.5)

    # Assert: no gap means no movement.
    assert drifted.valence == pytest.approx(0.3)
    assert drifted.social == pytest.approx(-0.1)


def test_drift_rate_must_be_within_unit_interval() -> None:
    # Arrange
    mood = Mood()

    # Act / Assert
    with pytest.raises(ValueError, match="rate"):
        mood.drift_toward(Mood(), rate=1.5)


def test_tone_for_positive_high_arousal_is_excited() -> None:
    # Arrange
    mood = Mood(valence=0.8, arousal=0.8)

    # Act
    tone = mood.tone()

    # Assert: positive valence + high arousal reads as upbeat/excited.
    assert tone == "excited"


def test_tone_for_negative_low_arousal_is_subdued() -> None:
    # Arrange
    mood = Mood(valence=-0.7, arousal=-0.6)

    # Act
    tone = mood.tone()

    # Assert
    assert tone == "subdued"


def test_tone_for_neutral_mood_is_neutral() -> None:
    # Arrange / Act
    tone = Mood().tone()

    # Assert
    assert tone == "neutral"


def test_tone_is_deterministic() -> None:
    # Arrange
    mood = Mood(valence=0.4, arousal=-0.3)

    # Act / Assert: same input → same descriptor, every time.
    assert mood.tone() == mood.tone()
