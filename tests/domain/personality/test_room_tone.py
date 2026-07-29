# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RoomMood→tone modulation (BOB-066 Срез 2.4, RFC Пласт 4).

A pure, deterministic SECOND LAYER (mirroring :mod:`bob.personality.mood_taste`):
the *room's* overall mood colours how playful Bob's voice reads and shifts his
appetite to jump in — WITHOUT ever touching Bob's personal :class:`Mood`. The room
mood arrives as plain floats (``room_valence`` / ``room_polarization``) passed by
the application from ``conversation``'s ``RoomReading`` — personality never imports
``conversation`` (no cycle).

Contract (the RFC guardrails):

* :func:`room_tone_directive` — a HEAVY (low-valence) OR POLARIZED (tense/split)
  room suppresses playfulness (a "read the room, dial it back" voice line); a warm,
  unpolarized room licenses a lighter tone; a neutral middle adds nothing (``""``),
  so the default path is unchanged.
* :func:`room_engagement_bias` — a signed shift to Bob's engagement threshold that
  REUSES the disposition contagion asymmetry: a warm room lifts his appetite MORE
  than an equally-cold room dampens it (``positive_lift_scale() > negative_dip_scale()``),
  the same structural anti-depressant. A flat room yields zero shift.

Both are temporary and pure: equal inputs → equal output, and the personal ``Mood``
is never mutated (these take floats, not a ``Mood``, by construction).
"""

from __future__ import annotations

import pytest

from bob.personality.disposition import Disposition
from bob.personality.room_tone import (
    RoomToneThresholds,
    room_engagement_bias,
    room_tone_directive,
)

# A clearly heavy room, a clearly warm room, a clearly polarized room, and a flat one.
_HEAVY_VALENCE = -0.7
_WARM_VALENCE = 0.7
_FLAT_VALENCE = 0.0
_CALM_POLARIZATION = 0.0
_TENSE_POLARIZATION = 0.8

_DISPOSITION = Disposition(optimism=0.8, resilience=0.7)


# --------------------------------------------------------------------------- #
# room_tone_directive                                                         #
# --------------------------------------------------------------------------- #


def test_neutral_room_adds_no_line() -> None:
    # A flat, unpolarized room neither suppresses nor lightens: the default voice
    # passes through with no extra directive.
    assert room_tone_directive(_FLAT_VALENCE, _CALM_POLARIZATION) == ""


def test_heavy_room_suppresses_playfulness() -> None:
    # A heavy (low-valence) room → a "dial back the playfulness / read the room"
    # line, and it must actually mention treading carefully (not the warm line).
    directive = room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    assert directive != ""
    assert directive != room_tone_directive(_WARM_VALENCE, _CALM_POLARIZATION)


def test_polarized_room_suppresses_playfulness_even_when_valence_positive() -> None:
    # A TENSE/split room suppresses playfulness even if the average valence is mildly
    # positive — polarization overrides warmth (a heated argument is not a party).
    heavy = room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    polarized = room_tone_directive(_WARM_VALENCE, _TENSE_POLARIZATION)
    assert polarized == heavy


def test_warm_unpolarized_room_licenses_a_lighter_tone() -> None:
    # A warm, calm room → a distinct lighter-tone line (not the suppression line,
    # not empty).
    warm = room_tone_directive(_WARM_VALENCE, _CALM_POLARIZATION)
    heavy = room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    assert warm != ""
    assert warm != heavy


def test_heavy_floor_boundary_is_inclusive() -> None:
    # At exactly the heavy floor the room already reads heavy; just above it does not.
    bands = RoomToneThresholds()
    assert room_tone_directive(bands.heavy_valence, _CALM_POLARIZATION) != ""
    just_above = bands.heavy_valence + 0.01
    # Just above the floor (still below the warm ceiling) → neutral, no line.
    assert room_tone_directive(just_above, _CALM_POLARIZATION) == ""


def test_warm_ceiling_boundary_is_inclusive() -> None:
    # At exactly the warm ceiling the room reads warm; just below adds no line.
    bands = RoomToneThresholds()
    warm = room_tone_directive(bands.warm_valence, _CALM_POLARIZATION)
    assert warm != ""
    assert warm != room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    just_below = bands.warm_valence - 0.01
    assert room_tone_directive(just_below, _CALM_POLARIZATION) == ""


def test_polarization_ceiling_boundary_is_inclusive() -> None:
    # At exactly the polarization ceiling the room reads tense (suppress); just below
    # a warm room stays warm.
    bands = RoomToneThresholds()
    suppressed = room_tone_directive(_WARM_VALENCE, bands.polarized)
    assert suppressed == room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    just_below = bands.polarized - 0.01
    assert room_tone_directive(_WARM_VALENCE, just_below) != suppressed


def test_directive_is_deterministic() -> None:
    # Same inputs → identical string, every time.
    assert room_tone_directive(_HEAVY_VALENCE, _TENSE_POLARIZATION) == room_tone_directive(
        _HEAVY_VALENCE, _TENSE_POLARIZATION
    )


def test_room_both_heavy_and_polarized_still_suppresses() -> None:
    # When BOTH OR-conditions are true (a heavy AND split room), the suppression line
    # still wins — the same "read the room" directive, never doubled or dropped.
    both = room_tone_directive(_HEAVY_VALENCE, _TENSE_POLARIZATION)
    heavy_only = room_tone_directive(_HEAVY_VALENCE, _CALM_POLARIZATION)
    assert both != ""
    assert both == heavy_only


def test_custom_thresholds_are_honoured() -> None:
    # Tighter bands move the boundary: a -0.2 room is neutral by default but heavy
    # under a lenient -0.1 floor.
    lenient = RoomToneThresholds(heavy_valence=-0.1)
    assert room_tone_directive(-0.2, _CALM_POLARIZATION) == ""
    assert room_tone_directive(-0.2, _CALM_POLARIZATION, thresholds=lenient) != ""


# --------------------------------------------------------------------------- #
# room_engagement_bias                                                        #
# --------------------------------------------------------------------------- #


def test_flat_room_yields_zero_bias() -> None:
    # A flat room shifts the engagement threshold not at all.
    assert room_engagement_bias(_FLAT_VALENCE, _DISPOSITION) == 0.0


def test_warm_room_biases_toward_engaging() -> None:
    # A warm room lifts Bob's appetite → a positive shift, scaled by the disposition
    # POSITIVE-lift magnitude.
    bias = room_engagement_bias(_WARM_VALENCE, _DISPOSITION)
    assert bias > 0.0
    assert bias == _WARM_VALENCE * _DISPOSITION.positive_lift_scale()


def test_cold_room_biases_away_from_engaging() -> None:
    # A heavy room dampens appetite → a negative shift, scaled by the (smaller)
    # NEGATIVE-dip magnitude.
    bias = room_engagement_bias(_HEAVY_VALENCE, _DISPOSITION)
    assert bias < 0.0
    assert bias == _HEAVY_VALENCE * _DISPOSITION.negative_dip_scale()


def test_bias_is_asymmetric_warm_lifts_more_than_cold_dips() -> None:
    # The structural anti-depressant: an equally-strong warm and cold room do NOT
    # cancel — the warm lift is strictly larger in magnitude than the cold dip.
    magnitude = 0.6
    lift = room_engagement_bias(magnitude, _DISPOSITION)
    dip = room_engagement_bias(-magnitude, _DISPOSITION)
    assert lift > -dip
    assert lift + dip > 0.0


def test_bias_scales_with_valence_magnitude() -> None:
    # A warmer room biases more than a mildly warm one (monotone in valence).
    assert room_engagement_bias(0.8, _DISPOSITION) > room_engagement_bias(0.3, _DISPOSITION)


def test_bias_is_deterministic() -> None:
    assert room_engagement_bias(0.5, _DISPOSITION) == room_engagement_bias(0.5, _DISPOSITION)


@pytest.mark.parametrize(
    "disposition",
    [
        Disposition(optimism=0.0, resilience=0.0),  # worst case: min lift, max dip
        Disposition(optimism=0.0, resilience=1.0),
        Disposition(optimism=1.0, resilience=0.0),
        Disposition(optimism=1.0, resilience=1.0),
        Disposition(optimism=0.8, resilience=0.7),  # canon
    ],
)
def test_bias_asymmetry_holds_for_every_disposition(disposition: Disposition) -> None:
    # The load-bearing claim is that room_engagement_bias REUSES the disposition
    # anti-depressant asymmetry — not that it merely coincides with it for canon. For
    # EVERY temperament (including the worst case, min-lift/max-dip), an equally-strong
    # warm and cold room must not cancel: the warm lift is strictly larger in magnitude.
    magnitude = 0.6
    lift = room_engagement_bias(magnitude, disposition)
    dip = room_engagement_bias(-magnitude, disposition)
    assert lift > 0.0 > dip
    assert lift > -dip
