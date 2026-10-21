# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmRoomReader — the Tier-1 realisation of the reflective seam (BOB-066 2.2).

The reader builds a Tier-1 ``ROOM_READ`` request from the pure prompt builder, runs it
on the preferred (API) provider, and parses the reply into a ``RoomReading``. On a parse
failure or a model/router error it RAISES (no silent default) — the periphery gate
catches it and safe-defaults to a silent IGNORE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.conversation.adapters.room_reader import LlmRoomReader
from bob.conversation.addressivity import Addressivity
from bob.conversation.room_reading import (
    ReflectiveIntent,
    RoomReadingContext,
)
from bob.conversation.room_reading_wire import RoomReadingParseError
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

_VALID = "situation: болтают\nintent: reply\nsalience: 0.8\nmood: warm"


class _FakeProvider:
    """A provider returning a fixed reply and recording the messages."""

    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises
        self.messages: Sequence[Mapping[str, str]] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        self.messages = messages
        if self._raises:
            raise RuntimeError("model down")
        return self._reply


def _context() -> RoomReadingContext:
    return RoomReadingContext(
        text="да ну, зонды скучные",
        interlocutor=Interlocutor(
            sender_id=6,
            display_name="Norman",
            kind=InterlocutorKind.KNOWN,
            trust=Trust.TRUSTED,
        ),
        recent_thread="Norman: привет\nbob: хай",
        mood_tone="ровный",
        addressivity=Addressivity.AMBIENT,
        mentions_bob=False,
        reply_to_bob=False,
        others_present=True,
        floor_engaged=False,
        floor_holder="other",
        floor_participant=True,
        interest=0.4,
    )


def _reader(reply: str, *, raises: bool = False) -> tuple[LlmRoomReader, _FakeProvider]:
    api = _FakeProvider(reply, raises=raises)
    # Tier 1 is preferred for ROOM_READ; the Tier-0 provider is present (router requires
    # it) but is only reached on a Tier-1 failure fallback.
    local = _FakeProvider("intent: ignore\nsalience: 0.0")
    router = LLMRouter(providers={0: local, 1: api})
    return LlmRoomReader(router=router), api


@pytest.mark.asyncio
async def test_builds_the_tier1_request_and_parses_the_reading() -> None:
    reader, provider = _reader(_VALID)
    reading = await reader.read(_context())
    assert reading.intent is ReflectiveIntent.REPLY
    assert reading.salience == pytest.approx(0.8)
    assert provider.messages is not None
    user_contents = " ".join(m["content"] for m in provider.messages)
    assert "да ну, зонды скучные" in user_contents


def test_room_read_is_pinned_tier1() -> None:
    assert TaskType.ROOM_READ.value == "room_read"


@pytest.mark.asyncio
async def test_raises_on_unparseable_reply() -> None:
    # A reply with no intent trips the parser on BOTH tiers (the local fallback also has
    # no usable intent here), so the failure surfaces for the periphery safe-default.
    api = _FakeProvider("I cannot read this room")
    local = _FakeProvider("still nothing")
    router = LLMRouter(providers={0: local, 1: api})
    reader = LlmRoomReader(router=router)
    with pytest.raises(RoomReadingParseError):
        await reader.read(_context())
