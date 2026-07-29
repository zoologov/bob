# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""RoomMood→tone modulation — the ROOM's mood colours Bob's voice (BOB-066, Пласт 4).

A pure, deterministic SECOND LAYER, mirroring :mod:`bob.personality.mood_taste`: on
TOP of Bob's personal mood/relationship tone, the *shared room's* atmosphere colours
how playful he sounds and how readily he jumps in — **without ever mutating his
personal** :class:`~bob.personality.mood.Mood`. This module consumes the room mood as
plain floats (``room_valence`` / ``room_polarization``), which the application layer
extracts from ``conversation``'s ``RoomReading`` and passes BY VALUE — so personality
never imports ``conversation`` (no import cycle; the pattern of
:data:`~bob.personality.voice._KIND_LABEL` keyed by ``kind.value``).

* :func:`room_tone_directive` — a HEAVY (low-valence) OR POLARIZED (tense/split) room
  suppresses playfulness: a "read the room, ease off the banter" voice line. A warm,
  unpolarized room licenses a lighter tone. A neutral middle adds nothing (``""``), so
  the default path stays unchanged. Polarization OVERRIDES warmth — a heated argument
  is never a party, whatever the average valence.
* :func:`room_engagement_bias` — a signed shift to Bob's engagement threshold that
  REUSES the disposition contagion asymmetry (:meth:`Disposition.positive_lift_scale`
  / :meth:`Disposition.negative_dip_scale`): a warm room lifts his appetite to speak
  MORE than an equally-cold room dampens it — the same structural anti-depressant. A
  flat room shifts nothing.

Both are module-level functions (deterministic, no I/O, no ``Mood``), so the personal
mood is untouched by construction and every transition is unit- and mutation-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.personality.disposition import Disposition

# Room-mood bands. The heavy floor / warm ceiling mirror the ±0.35 dead-band of
# :mod:`mood_taste` — an ordinary room is a clean identity (no jitter). Polarization
# is a separate [0, 1] tension axis; at/above the ceiling the room reads split/heated
# regardless of the average valence.
_DEFAULT_HEAVY_VALENCE = -0.35
_DEFAULT_WARM_VALENCE = 0.35
_DEFAULT_POLARIZED = 0.5

# A flat room contributes no engagement shift at all (the dead-centre of the axis).
_NO_BIAS = 0.0

# Room-tone voice lines (project language: Russian; Cyrillic look-alikes intentional).
# Written as VOICE (how Bob reads the room), never a config switch — callers/tests pin
# presence/shape, not wording.
_ROOM_HEAVY_OR_TENSE = (
    "Атмосфера в комнате сейчас тяжёлая — напряжённо или на взводе. Считай "
    "обстановку и сбавь игривость: без подколов и трёпа «ни о чём», говори "
    "внимательнее и мягче, как человек, который чувствует, что момент не для "
    "балагана. Это не значит замкнуться — просто быть к месту."
)
_ROOM_WARM = (
    "В комнате сейчас тепло и расслабленно — можно и полегче: живой, свободный "
    "тон, лёгкая шутка к месту, если в настроении. Без наигранности — просто "
    "поймал волну."
)


@dataclass(frozen=True, slots=True)
class RoomToneThresholds:
    """The room-mood bands at which Bob's voice eases off / lightens (BOB-066).

    A room whose ``room_valence`` is at-or-below ``heavy_valence`` reads heavy; at-or-
    above ``warm_valence`` reads warm (and lightens the tone) — but ONLY when the room
    is not polarized. A ``room_polarization`` at-or-above ``polarized`` reads the room
    as tense/split and suppresses playfulness regardless of valence. Between the bands
    no colour is added, so the default path is unchanged. The application tunes them
    from ``presence.room_tone.*`` config.
    """

    heavy_valence: float = _DEFAULT_HEAVY_VALENCE
    warm_valence: float = _DEFAULT_WARM_VALENCE
    polarized: float = _DEFAULT_POLARIZED


def room_tone_directive(
    room_valence: float,
    room_polarization: float,
    *,
    thresholds: RoomToneThresholds | None = None,
) -> str:
    """Return the room-mood voice line for this turn, or ``""`` (neutral room).

    On TOP of Bob's personal mood/relationship tone, the shared room's atmosphere
    colours his voice: a HEAVY (``room_valence`` at/below the ``heavy_valence`` floor)
    OR POLARIZED (``room_polarization`` at/above the ``polarized`` ceiling) room
    suppresses playfulness — a "read the room, ease off the banter" line; a warm,
    unpolarized room (``room_valence`` at/above ``warm_valence``) licenses a lighter
    tone; a neutral middle adds nothing (``""``). Polarization OVERRIDES warmth (a
    heated argument is never a party). Pure and deterministic; the personal ``Mood`` is
    never touched. The bands are config-tunable via :class:`RoomToneThresholds`.
    """
    bands = thresholds if thresholds is not None else RoomToneThresholds()
    if room_polarization >= bands.polarized or room_valence <= bands.heavy_valence:
        return _ROOM_HEAVY_OR_TENSE
    if room_valence >= bands.warm_valence:
        return _ROOM_WARM
    return ""


def room_engagement_bias(room_valence: float, disposition: Disposition) -> float:
    """Return the signed shift to Bob's engagement threshold from the room mood (BOB-066).

    A warm room (positive ``room_valence``) lifts Bob's appetite to jump in → a
    POSITIVE shift; a heavy room (negative valence) dampens it → a NEGATIVE shift; a
    flat room shifts nothing. The magnitudes REUSE the disposition social-contagion
    asymmetry — a warm room scales by :meth:`Disposition.positive_lift_scale` and a
    cold one by the strictly-smaller :meth:`Disposition.negative_dip_scale`, so an
    equally-strong warm and cold room do NOT cancel: warmth moves Bob more than
    coldness, the same structural anti-depressant. Pure and deterministic; equal
    inputs → equal shift.
    """
    if room_valence > _NO_BIAS:
        return room_valence * disposition.positive_lift_scale()
    if room_valence < _NO_BIAS:
        return room_valence * disposition.negative_dip_scale()
    return _NO_BIAS
