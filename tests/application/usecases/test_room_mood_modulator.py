# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RoomMoodModulator — the application bridge for «RoomMood-в-тоне» (BOB-066 W.2).

The collaborator maps the reflective room's mood primitives (valence/polarization, passed
BY VALUE from ``conversation``'s ``RoomReading``) to the pure personality decisions — a tone
line (:func:`room_tone_directive`) + a signed engagement-threshold shift
(:func:`room_engagement_bias`) — so ``personality`` never imports ``conversation``. Bob's
personal ``Mood`` is never touched (a SECOND layer, by construction — these take floats).
"""

from __future__ import annotations

from bob.application.usecases.room_mood_modulator import RoomMoodModulator
from bob.conversation.room_reading import RoomMood
from bob.personality.disposition import Disposition
from bob.personality.room_tone import RoomToneThresholds

_MODULATOR = RoomMoodModulator(
    disposition=Disposition.canonical(),
    thresholds=RoomToneThresholds(),
)


def test_heavy_room_tone_line_eases_the_banter() -> None:
    mood = RoomMood.SOMBRE  # low valence → heavy

    line = _MODULATOR.tone_line(mood.valence, mood.polarization)

    assert line != ""
    assert "игривость" in line


def test_polarized_room_tone_line_eases_even_at_mild_positive_valence() -> None:
    mood = RoomMood.HEATED  # split/heated → polarized overrides warmth

    line = _MODULATOR.tone_line(mood.valence, mood.polarization)

    assert line != ""


def test_warm_room_tone_line_lightens() -> None:
    mood = RoomMood.WARM

    line = _MODULATOR.tone_line(mood.valence, mood.polarization)

    assert line != ""
    assert "легч" in line or "лёгк" in line


def test_neutral_room_adds_no_tone_line() -> None:
    mood = RoomMood.NEUTRAL

    assert _MODULATOR.tone_line(mood.valence, mood.polarization) == ""


def test_warm_room_lifts_appetite_more_than_cold_dampens() -> None:
    # The disposition contagion asymmetry: an equally-strong warm and cold room do NOT cancel.
    warm_shift = _MODULATOR.engagement_shift(0.6)
    cold_shift = _MODULATOR.engagement_shift(-0.6)

    assert warm_shift > 0.0
    assert cold_shift < 0.0
    assert warm_shift > -cold_shift


def test_flat_room_shifts_nothing() -> None:
    assert _MODULATOR.engagement_shift(0.0) == 0.0
