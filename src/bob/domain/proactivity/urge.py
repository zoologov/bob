# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity-domain

"""UrgeModel — the pure "drive to reach out" formula (no I/O, no LLM, no clock).

``urge(...)`` combines four named, tunable drives into a single ``[0, 1]`` score:

* **mood** — an aroused, open, social mood lifts the urge; a withdrawn one lowers it,
* **longing** — grows with ``silence_seconds`` (saturating, so it never runs away),
* **salience** — how striking a fresh reflection is right now, and
* **circadian** — a baseline keyed to the local hour: low at night, bimodal peaks
  in the morning and evening bracketing a midday dip.

Each drive has a named weight; the weighted sum is squashed into ``[0, 1]``. The
function is deterministic and pure — the same inputs always yield the same urge,
so it is unit-testable without any model, and time-of-day arrives as an already
clock-derived ``time_of_day_local`` rather than being read here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.personality.mood import Mood

# Input bounds.
_MIN_SALIENCE = 0.0
_MAX_SALIENCE = 1.0
_MIN_ENERGY = 0.0
_MAX_ENERGY = 1.0
_MIN_HOUR = 0
_MAX_HOUR = 23

# Longing saturates: at this many seconds of silence it reaches ~63% of full,
# so a day of quiet is strongly felt without ever exceeding the cap.
_LONGING_TIME_CONSTANT_SECONDS = 6.0 * 3600.0

# Named drive weights (tunable). They sum the four pulls before squashing.
_W_MOOD = 0.30
_W_LONGING = 0.30
_W_SALIENCE = 0.20
_W_CIRCADIAN = 0.20
_W_ENERGY = 0.20

# Circadian baseline per local hour in [0, 1]: a flat-low night, a morning rise,
# a midday dip, and an evening peak. Tunable; the curve, not the numbers, matters.
_CIRCADIAN_BY_HOUR: tuple[float, ...] = (
    0.05,  # 00
    0.05,  # 01
    0.05,  # 02
    0.05,  # 03
    0.05,  # 04
    0.10,  # 05
    0.25,  # 06
    0.55,  # 07
    0.80,  # 08
    0.95,  # 09  morning peak
    0.85,  # 10
    0.70,  # 11
    0.55,  # 12
    0.45,  # 13
    0.40,  # 14  midday dip
    0.45,  # 15
    0.55,  # 16
    0.70,  # 17
    0.85,  # 18
    0.95,  # 19
    1.00,  # 20  evening peak
    0.80,  # 21
    0.45,  # 22
    0.15,  # 23
)


def _mood_drive(mood: Mood) -> float:
    """Map mood to a [0, 1] outgoingness from its arousal, openness, and social axes.

    Each axis lives in [-1, 1]; their mean is rescaled to [0, 1] so a withdrawn
    mood pulls the urge down and an open, aroused, social one pulls it up.
    """
    axis_mean = (mood.arousal + mood.openness + mood.social) / 3.0
    return (axis_mean + 1.0) / 2.0


def _longing_drive(silence_seconds: float) -> float:
    """Map silence to a [0, 1) longing that grows and saturates with time apart."""
    return 1.0 - math.exp(-silence_seconds / _LONGING_TIME_CONSTANT_SECONDS)


@dataclass(frozen=True, slots=True)
class UrgeModel:
    """The pure drive-to-reach-out formula combining mood, longing, salience, circadian."""

    def urge(
        self,
        *,
        mood: Mood,
        silence_seconds: float,
        salience: float,
        time_of_day_local: int,
        social_energy: float,
    ) -> float:
        """Return Bob's drive to reach out, in ``[0, 1]``.

        Combines the mood, longing, salience, circadian, and energy drives by
        their named weights and squashes the result into the unit interval.
        """
        self._validate(
            silence_seconds=silence_seconds,
            salience=salience,
            time_of_day_local=time_of_day_local,
            social_energy=social_energy,
        )
        weighted = (
            _W_MOOD * _mood_drive(mood)
            + _W_LONGING * _longing_drive(silence_seconds)
            + _W_SALIENCE * salience
            + _W_CIRCADIAN * _CIRCADIAN_BY_HOUR[time_of_day_local]
            + _W_ENERGY * social_energy
        )
        total_weight = _W_MOOD + _W_LONGING + _W_SALIENCE + _W_CIRCADIAN + _W_ENERGY
        return weighted / total_weight

    @staticmethod
    def _validate(
        *,
        silence_seconds: float,
        salience: float,
        time_of_day_local: int,
        social_energy: float,
    ) -> None:
        if silence_seconds < 0.0:
            raise ValueError(f"silence seconds must be non-negative, got {silence_seconds}")
        if not _MIN_SALIENCE <= salience <= _MAX_SALIENCE:
            raise ValueError(
                f"salience must be within [{_MIN_SALIENCE}, {_MAX_SALIENCE}], got {salience}"
            )
        if not _MIN_ENERGY <= social_energy <= _MAX_ENERGY:
            raise ValueError(
                f"social energy must be within [{_MIN_ENERGY}, {_MAX_ENERGY}], "
                f"got {social_energy}"
            )
        if not _MIN_HOUR <= time_of_day_local <= _MAX_HOUR:
            raise ValueError(
                f"local hour must be within [{_MIN_HOUR}, {_MAX_HOUR}], got {time_of_day_local}"
            )
