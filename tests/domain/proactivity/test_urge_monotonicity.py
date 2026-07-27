# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Table-driven monotonicity hardening for the UrgeModel (BOB-010 Ф1, US-1).

US-1 acceptance: the proactive urge rises with mood, longing (silence), salience,
and the circadian baseline. The companion ``test_urge`` file pins each axis with a
two-point comparison; this file hardens that into **table-driven, strictly
monotonic** checks across an ordered grid of values for one axis at a time, holding
the others fixed. A regression that flattens, inverts, or non-monotonically warps
any single drive is caught here, not just at the two endpoints.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from bob.domain.personality.mood import Mood
from bob.proactivity.urge import UrgeModel

# A neutral fixed point: every axis below varies against this baseline so only the
# axis under test moves.
_NEUTRAL_MOOD = Mood()
_MIDDAY = 12


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


def _assert_strictly_increasing(values: list[float]) -> None:
    """Assert the sequence rises at every step (no flat or inverted segment)."""
    for earlier, later in pairwise(values):
        assert later > earlier, f"expected strictly increasing, got {values}"


# An ordered ladder of silence durations from a minute to two days.
_SILENCE_LADDER = [60.0, 600.0, 3600.0, 6.0 * 3600.0, 24.0 * 3600.0, 48.0 * 3600.0]
# An ordered ladder of salience values across the whole unit interval.
_SALIENCE_LADDER = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
# An ordered ladder of social-energy values across the whole unit interval.
_ENERGY_LADDER = [0.0, 0.25, 0.5, 0.75, 1.0]
# An ordered ladder of mood outgoingness (all three axes moved together).
_MOOD_AXIS_LADDER = [-1.0, -0.5, 0.0, 0.5, 1.0]


def test_urge_strictly_increases_along_silence_ladder() -> None:
    # Act: only longing (silence) moves across the ladder.
    urges = [_urge(silence_seconds=seconds) for seconds in _SILENCE_LADDER]

    # Assert: longing pulls the urge up at every step.
    _assert_strictly_increasing(urges)


def test_urge_strictly_increases_along_salience_ladder() -> None:
    # Act: only the fresh-reflection salience moves.
    urges = [_urge(salience=salience) for salience in _SALIENCE_LADDER]

    # Assert
    _assert_strictly_increasing(urges)


def test_urge_strictly_increases_along_energy_ladder() -> None:
    # Act: only the social-energy reservoir moves.
    urges = [_urge(social_energy=energy) for energy in _ENERGY_LADDER]

    # Assert
    _assert_strictly_increasing(urges)


def test_urge_strictly_increases_along_mood_outgoingness_ladder() -> None:
    # Act: arousal/openness/social move together from withdrawn to outgoing.
    urges = [
        _urge(mood=Mood(arousal=axis, openness=axis, social=axis))
        for axis in _MOOD_AXIS_LADDER
    ]

    # Assert: a more outgoing mood lifts the urge at every step.
    _assert_strictly_increasing(urges)


# The circadian curve is bimodal (morning + evening peaks bracket a midday dip), so
# it is monotonic only *segment by segment*. Each row pins an ordered sub-sequence
# of hours and its expected direction (the urge rises into a peak, falls into a dip
# or into the night). A "falling" segment is checked strictly increasing in reverse.
@pytest.mark.parametrize(
    ("label", "hours", "rising"),
    [
        ("predawn_rise_to_morning_peak", [4, 6, 7, 8, 9], True),
        ("morning_peak_into_midday_dip", [9, 11, 13, 14], False),
        ("afternoon_rise_to_evening_peak", [14, 16, 18, 20], True),
        ("evening_peak_into_night", [20, 22, 23], False),
    ],
)
def test_circadian_is_monotonic_within_each_segment(
    label: str, hours: list[int], rising: bool
) -> None:
    assert label  # the segment id, present for readable parametrize output
    # Act: same state, only the local hour walks the segment.
    urges = [_urge(time_of_day_local=hour) for hour in hours]

    # Assert: a rising segment rises; a falling one is strictly increasing reversed.
    _assert_strictly_increasing(urges if rising else list(reversed(urges)))


def test_circadian_night_floor_is_the_global_minimum() -> None:
    # Act: the deepest night hours against the evening peak.
    night_hours = [_urge(time_of_day_local=hour) for hour in range(0, 5)]
    evening_peak = _urge(time_of_day_local=20)

    # Assert: every small-hour urge sits below the evening peak (a hard night floor).
    assert max(night_hours) < evening_peak
