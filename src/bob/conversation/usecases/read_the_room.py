# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""ReadTheRoom — assemble the context and ask the reflective reader (BOB-066 Срез 2.2).

The thin application use-case over the reflective «read the room» seam, mirroring
:class:`~bob.conversation.usecases.decide_response.DecideResponse` (BOB-049): it gathers
the periphery turn's pieces (the message, the sender as social context, the shared
author-labelled thread, the mood tone, the structural + floor HINTS and Bob's topic
interest) into a :class:`~bob.conversation.room_reading.RoomReadingContext` and delegates
the single rich read to the injected
:class:`~bob.conversation.room_reading.RoomReader`. It holds no policy of its own — the
verdict is decided PURELY downstream by
:func:`~bob.conversation.room_verdict.decide_from_reading` — so the meaning-read lives
entirely behind the (deterministic-in-tests) seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.room_reading import RoomReadingContext

if TYPE_CHECKING:
    from bob.conversation.addressivity import Addressivity
    from bob.conversation.room_reading import RoomReader, RoomReading
    from bob.kernel.interlocutor import Interlocutor

__all__ = ["ReadTheRoom"]


class ReadTheRoom:
    """Assemble a :class:`RoomReadingContext` and read the room via the injected reader."""

    def __init__(self, *, reader: RoomReader) -> None:
        self._reader = reader

    async def read(
        self,
        *,
        text: str,
        interlocutor: Interlocutor,
        recent_thread: str,
        mood_tone: str,
        addressivity: Addressivity,
        mentions_bob: bool,
        reply_to_bob: bool,
        others_present: bool,
        floor_engaged: bool,
        floor_holder: str,
        floor_participant: bool,
        interest: float,
    ) -> RoomReading:
        """Assemble the periphery turn's context and return the reader's :class:`RoomReading`.

        Every structural / floor argument and the topic ``interest`` are carried into the
        context as HINTS the reflection weighs by meaning — none forces the outcome.
        """
        ctx = RoomReadingContext(
            text=text,
            interlocutor=interlocutor,
            recent_thread=recent_thread,
            mood_tone=mood_tone,
            addressivity=addressivity,
            mentions_bob=mentions_bob,
            reply_to_bob=reply_to_bob,
            others_present=others_present,
            floor_engaged=floor_engaged,
            floor_holder=floor_holder,
            floor_participant=floor_participant,
            interest=interest,
        )
        return await self._reader.read(ctx)
