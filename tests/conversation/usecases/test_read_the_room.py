# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ReadTheRoom use-case (BOB-066 Срез 2.2).

The thin application seam over the reflective reader: it must assemble every argument
into a :class:`RoomReadingContext` and delegate to the injected port unchanged — no
policy of its own.
"""

from __future__ import annotations

import pytest

from bob.conversation.addressivity import Addressivity
from bob.conversation.room_reading import (
    ReflectiveIntent,
    RoomMood,
    RoomReading,
    RoomReadingContext,
)
from bob.conversation.usecases.read_the_room import ReadTheRoom
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust

_READING = RoomReading(
    situation="болтают",
    pairings=(),
    room_mood=RoomMood.WARM,
    intent=ReflectiveIntent.IGNORE,
    addressee_id=None,
    salience=0.2,
    emoji=None,
    wants_web=False,
    reason="r",
)


class _CapturingReader:
    """A fake RoomReader that records the context it was handed."""

    def __init__(self) -> None:
        self.ctx: RoomReadingContext | None = None

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        self.ctx = ctx
        return _READING


def _interlocutor() -> Interlocutor:
    return Interlocutor(
        sender_id=6,
        display_name="Norman",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )


@pytest.mark.asyncio
async def test_assembles_the_context_and_returns_the_readers_reading() -> None:
    reader = _CapturingReader()
    reading = await ReadTheRoom(reader=reader).read(
        text="да ну",
        interlocutor=_interlocutor(),
        recent_thread="Norman: привет",
        mood_tone="ровный",
        addressivity=Addressivity.AMBIENT,
        mentions_bob=False,
        reply_to_bob=False,
        others_present=True,
        floor_engaged=True,
        floor_holder="bob",
        floor_participant=True,
        interest=0.5,
    )
    assert reading is _READING
    assert reader.ctx is not None
    assert reader.ctx.text == "да ну"
    assert reader.ctx.addressivity is Addressivity.AMBIENT
    assert reader.ctx.floor_holder == "bob"
    assert reader.ctx.floor_participant is True
    assert reader.ctx.interest == 0.5
