# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root room-mood wiring — «RoomMood-в-тоне» behind ``presence.room_mood``.

The room-mood consumption seam (BOB-066 Срез W.2): this is the ONE place the
``presence.room_mood`` flag is read and the
:class:`~bob.application.usecases.room_mood_modulator.RoomMoodModulator` is assembled from
Bob's disposition + the ``presence.room_mood.*`` tone bands. Off (the default — the whole
«человеческое групповое присутствие» epic ships as one piece) the modulator is ``None`` so
the reflective room-mood never colours a turn and Bob is byte-identical.

The flag follows the nested ``<section>.enabled`` convention (a flag WITH sub-knobs): the
tone bands live under ``presence.room_mood.{heavy_valence,warm_valence,polarized}`` and
default to the gentle :class:`~bob.personality.room_tone.RoomToneThresholds` defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.usecases.room_mood_modulator import RoomMoodModulator
from bob.personality.room_tone import RoomToneThresholds
from bob.runtime.config import _flag, _float_or, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.personality.disposition import Disposition


def build_room_mood_modulator(
    config: Mapping[str, object], *, disposition: Disposition
) -> RoomMoodModulator | None:
    """Assemble the room-mood modulator, or ``None`` when ``presence.room_mood`` is off.

    Reads ``presence.room_mood.enabled`` (off by default): off → ``None`` so the hot path
    is byte-identical (the reflective room mood is inert). On → builds the
    :class:`RoomMoodModulator` over Bob's ``disposition`` (for the warm-lifts-more-than-cold
    engagement asymmetry) and the tone bands under ``presence.room_mood.*``.
    """
    presence = _section(config, "presence")
    room = _section(presence, "room_mood")
    if not _flag(room, "enabled"):
        return None
    base = RoomToneThresholds()
    thresholds = RoomToneThresholds(
        heavy_valence=_float_or(room, "heavy_valence", base.heavy_valence),
        warm_valence=_float_or(room, "warm_valence", base.warm_valence),
        polarized=_float_or(room, "polarized", base.polarized),
    )
    return RoomMoodModulator(disposition=disposition, thresholds=thresholds)
