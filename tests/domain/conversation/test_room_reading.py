# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the reflective read value types (BOB-066 Срез 2.2).

Pins the :class:`RoomMood` valence/polarization tables (the primitives a later slice
consumes BY VALUE in the tone) and the intent surface — total mappings the gate + tone
depend on.
"""

from __future__ import annotations

import pytest

from bob.conversation.room_reading import ReflectiveIntent, RoomMood


@pytest.mark.parametrize("mood", list(RoomMood))
def test_every_mood_exposes_a_valence_in_the_signed_unit_interval(
    mood: RoomMood,
) -> None:
    assert -1.0 <= mood.valence <= 1.0


@pytest.mark.parametrize("mood", list(RoomMood))
def test_every_mood_exposes_a_polarization_in_the_unit_interval(mood: RoomMood) -> None:
    assert 0.0 <= mood.polarization <= 1.0


def test_a_warm_room_is_positive_and_calm() -> None:
    assert RoomMood.WARM.valence > 0.0
    assert RoomMood.WARM.polarization < 0.5


def test_a_heated_room_is_negative_and_highly_polarized() -> None:
    assert RoomMood.HEATED.valence < 0.0
    assert RoomMood.HEATED.polarization > 0.5


def test_a_neutral_room_is_flat() -> None:
    assert RoomMood.NEUTRAL.valence == 0.0
    assert RoomMood.NEUTRAL.polarization == 0.0


def test_playful_is_the_warmest_room() -> None:
    assert RoomMood.PLAYFUL.valence == max(m.valence for m in RoomMood)


def test_reflective_intent_has_the_five_named_choices() -> None:
    assert {i.value for i in ReflectiveIntent} == {
        "reply",
        "react",
        "ignore",
        "initiate",
        "self_check",
    }
