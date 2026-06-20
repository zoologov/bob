# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for UrgeModel — the pure drive-to-reach-out formula (no I/O, no LLM)."""

from __future__ import annotations

import pytest

from bob.domain.personality.mood import Mood
from bob.domain.proactivity.urge import UrgeModel

# A neutral mood and mid-day baseline used as the fixed point for monotonicity.
_NEUTRAL_MOOD = Mood()
_MIDDAY = 12
_NIGHT = 3


def _urge(
    *,
    mood: Mood = _NEUTRAL_MOOD,
    silence_seconds: float = 1800.0,
    salience: float = 0.0,
    time_of_day_local: int = _MIDDAY,
    social_energy: float = 0.5,
) -> float:
    return UrgeModel().urge(
        mood=mood,
        silence_seconds=silence_seconds,
        salience=salience,
        time_of_day_local=time_of_day_local,
        social_energy=social_energy,
    )


def test_urge_is_bounded_to_unit_interval() -> None:
    # Arrange: extreme inputs in both directions.
    high = _urge(
        mood=Mood(arousal=1.0, openness=1.0, social=1.0),
        silence_seconds=1_000_000.0,
        salience=1.0,
        time_of_day_local=9,
        social_energy=1.0,
    )
    low = _urge(
        mood=Mood(arousal=-1.0, openness=-1.0, social=-1.0),
        silence_seconds=0.0,
        salience=0.0,
        time_of_day_local=_NIGHT,
        social_energy=0.0,
    )

    # Assert
    assert 0.0 <= low <= high <= 1.0


def test_urge_rises_with_silence() -> None:
    # Act
    short = _urge(silence_seconds=60.0)
    long = _urge(silence_seconds=86_400.0)

    # Assert: longing grows with silence.
    assert long > short


def test_urge_rises_with_salience() -> None:
    # Act
    dull = _urge(salience=0.0)
    salient = _urge(salience=1.0)

    # Assert: a salient fresh reflection raises the urge.
    assert salient > dull


def test_urge_rises_with_social_mood() -> None:
    # Act
    withdrawn = _urge(mood=Mood(arousal=-0.8, openness=-0.8, social=-0.8))
    outgoing = _urge(mood=Mood(arousal=0.8, openness=0.8, social=0.8))

    # Assert: an open, aroused, social mood lifts the urge.
    assert outgoing > withdrawn


def test_urge_rises_with_social_energy() -> None:
    # Act
    drained = _urge(social_energy=0.0)
    charged = _urge(social_energy=1.0)

    # Assert: more reservoir → more urge to spend it.
    assert charged > drained


def test_circadian_night_is_lower_than_morning() -> None:
    # Act: same state, only the clock differs.
    night = _urge(time_of_day_local=_NIGHT)
    morning = _urge(time_of_day_local=9)

    # Assert: the circadian baseline suppresses the small hours.
    assert night < morning


def test_circadian_peaks_morning_and_evening() -> None:
    # Act
    morning = _urge(time_of_day_local=9)
    midday = _urge(time_of_day_local=14)
    evening = _urge(time_of_day_local=20)

    # Assert: a bimodal day — peaks bracket a midday dip.
    assert morning > midday
    assert evening > midday


def test_urge_is_deterministic() -> None:
    # Act / Assert: same inputs → identical output, no hidden state.
    assert _urge(silence_seconds=1234.0, salience=0.3) == _urge(
        silence_seconds=1234.0, salience=0.3
    )


def test_urge_rejects_out_of_range_salience() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="salience"):
        _urge(salience=1.5)


def test_urge_rejects_out_of_range_social_energy() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="social energy"):
        _urge(social_energy=-0.2)


def test_urge_rejects_negative_silence() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="silence"):
        _urge(silence_seconds=-1.0)


def test_urge_rejects_out_of_range_hour() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="hour"):
        _urge(time_of_day_local=24)
