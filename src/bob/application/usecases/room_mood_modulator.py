# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app
# beadloom:layer=application

"""RoomMoodModulator — the room's mood colours Bob's voice + appetite (BOB-066 Срез W.2).

The application bridge for «RoomMood-в-тоне» (Пласт 4): the reflective «read the room»
(conversation) hands up the room's atmosphere as a
:class:`~bob.conversation.room_reading.RoomMood`, and this collaborator maps its plain
primitives (``valence`` / ``polarization``, extracted by
:class:`~bob.application.usecases.handle_message.HandleMessage` and passed BY VALUE) into
the pure personality decisions:

* :meth:`tone_line` → :func:`~bob.personality.room_tone.room_tone_directive` — a HEAVY or
  POLARIZED room suppresses playfulness, a warm one lightens the tone (``""`` on a neutral
  room, so the default compose path is unchanged);
* :meth:`engagement_shift` → :func:`~bob.personality.room_tone.room_engagement_bias` — a
  signed shift to Bob's engagement threshold (a warm room lifts his appetite MORE than an
  equally-cold one dampens it, reusing the disposition contagion asymmetry).

🔴 It lives in application because it is the ONLY place both bounded contexts meet — it
reads the ``RoomMood`` floats (conversation) and calls the pure personality functions
(personality) — so ``personality`` never imports ``conversation`` (no cycle). Bob's
personal :class:`~bob.personality.mood.Mood` is NEVER mutated: RoomMood is a SECOND layer
that only shapes this turn's voice/appetite. Wired ONLY behind ``presence.room_mood.enabled``
(OFF by default → not built → the seam is inert and the turn is byte-identical).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.personality.room_tone import room_engagement_bias, room_tone_directive

if TYPE_CHECKING:
    from bob.personality.disposition import Disposition
    from bob.personality.room_tone import RoomToneThresholds

__all__ = ["RoomMoodModulator"]


@dataclass(frozen=True, slots=True)
class RoomMoodModulator:
    """Map the room's mood primitives to Bob's tone line + engagement shift (BOB-066 W.2)."""

    disposition: Disposition
    thresholds: RoomToneThresholds

    def tone_line(self, room_valence: float, room_polarization: float) -> str:
        """Return the room-mood voice line for this turn, or ``""`` on a neutral room."""
        return room_tone_directive(
            room_valence, room_polarization, thresholds=self.thresholds
        )

    def engagement_shift(self, room_valence: float) -> float:
        """Return the signed engagement-threshold shift the room's warmth earns this turn."""
        return room_engagement_bias(room_valence, self.disposition)
