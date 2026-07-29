# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the RoomMood-в-тоне acceptance scenarios (BOB-066 Срез 2.4).

Binds the Gherkin steps of ``room_tone.feature`` to the pure personality room-tone
layer. RoomMood is a SECOND layer: the room arrives as floats (valence/polarization)
that the application extracts from ``conversation``'s ``RoomReading`` and passes by
value — so these steps drive the pure ``room_tone`` functions directly and assert the
observable voice line, PLUS the load-bearing invariant that Bob's personal
:class:`Mood` is never mutated by the room colouring (living documentation for the
no-cycle, no-mutation contract of Пласт 4).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.room_tone import room_engagement_bias, room_tone_directive

scenarios("../features/room_tone.feature")

_DISPOSITION = Disposition(optimism=0.8, resilience=0.7)


class _RoomToneContext:
    """Carries the personal mood snapshot + the room's floats across BDD steps."""

    def __init__(self) -> None:
        self.mood = Mood(valence=0.7, arousal=0.4, openness=0.6)
        self.mood_before = replace(self.mood)
        self.room_valence = 0.0
        self.room_polarization = 0.0
        self.directive = ""

    def read_room(self) -> None:
        """Apply the room colouring — the SECOND layer never touches the personal mood."""
        self.directive = room_tone_directive(self.room_valence, self.room_polarization)
        # The engagement bias reads the SAME floats; exercising it proves the personal
        # mood is an input to neither path (both take floats, never the ``Mood``).
        room_engagement_bias(self.room_valence, _DISPOSITION)


@pytest.fixture
def room_tone_context() -> _RoomToneContext:
    return _RoomToneContext()


@given("личное настроение Боба светлое и открытое")
def bright_personal_mood(room_tone_context: _RoomToneContext) -> None:
    assert room_tone_context.mood.valence > 0


@when("комната читается тяжёлой и подавленной")
def heavy_room(room_tone_context: _RoomToneContext) -> None:
    room_tone_context.room_valence = -0.7
    room_tone_context.room_polarization = 0.0
    room_tone_context.read_room()


@when("комната читается накалённой и расколотой, хотя средний фон мягко-плюсовой")
def polarized_room(room_tone_context: _RoomToneContext) -> None:
    room_tone_context.room_valence = 0.7
    room_tone_context.room_polarization = 0.8
    room_tone_context.read_room()


@when("комната читается тёплой и расслабленной")
def warm_room(room_tone_context: _RoomToneContext) -> None:
    room_tone_context.room_valence = 0.7
    room_tone_context.room_polarization = 0.0
    room_tone_context.read_room()


@when("комната читается ровной и спокойной")
def neutral_room(room_tone_context: _RoomToneContext) -> None:
    room_tone_context.room_valence = 0.0
    room_tone_context.room_polarization = 0.0
    room_tone_context.read_room()


@then("тон-директива велит сбавить игривость и считать обстановку")
def directive_suppresses_playfulness(room_tone_context: _RoomToneContext) -> None:
    assert room_tone_context.directive != ""
    # It must be the suppression line, distinct from the warm (lighter-tone) line.
    warm = room_tone_directive(0.7, 0.0)
    assert room_tone_context.directive != warm


@then("тон-директива разрешает более лёгкий, живой тон")
def directive_licenses_lighter_tone(room_tone_context: _RoomToneContext) -> None:
    assert room_tone_context.directive != ""
    heavy = room_tone_directive(-0.7, 0.0)
    assert room_tone_context.directive != heavy


@then(parsers.parse("тон-директива пуста и тон Боба не меняется"))
def directive_is_empty(room_tone_context: _RoomToneContext) -> None:
    assert room_tone_context.directive == ""


@then("личное настроение Боба остаётся прежним")
def personal_mood_unchanged(room_tone_context: _RoomToneContext) -> None:
    assert room_tone_context.mood == room_tone_context.mood_before
