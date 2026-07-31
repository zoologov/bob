# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmBatchRoomReader — the Tier-1 realisation of the batch stream-read (BOB-072).

The reader builds ONE Tier-1 ``ROOM_READ`` request from the pure batch prompt over a whole
ambient burst, runs it, and parses the reply into per-message readings. The batch parser is
TOLERANT, so a garbled reply yields a safe all-IGNORE plan of the right length rather than a
raise. An empty burst never calls the model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.conversation.adapters.room_reader import LlmBatchRoomReader
from bob.conversation.room_reading import (
    BatchAmbientMessage,
    BatchRoomReadingContext,
    ReflectiveIntent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """A provider returning a fixed reply and recording the messages it saw."""

    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises
        self.messages: Sequence[Mapping[str, str]] | None = None
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        self.messages = messages
        if self._raises:
            raise RuntimeError("model down")
        return self._reply


def _msg(sender_id: int, sender_name: str, text: str) -> BatchAmbientMessage:
    return BatchAmbientMessage(
        sender_id=sender_id,
        sender_name=sender_name,
        text=text,
        ts=0.0,
        floor_holder="other",
        floor_participant=True,
        interest=0.4,
    )


def _ctx(*messages: BatchAmbientMessage) -> BatchRoomReadingContext:
    return BatchRoomReadingContext(
        messages=tuple(messages),
        recent_thread="Norman: привет",
        mood_tone="ровный",
        others_present=True,
    )


def _reader(reply: str, *, raises: bool = False) -> tuple[LlmBatchRoomReader, _FakeProvider]:
    api = _FakeProvider(reply, raises=raises)
    local = _FakeProvider("intent: ignore\nsalience: 0.0")
    router = LLMRouter(providers={0: local, 1: api})
    return LlmBatchRoomReader(router=router), api


@pytest.mark.asyncio
async def test_reads_a_burst_into_per_message_decisions() -> None:
    reply = (
        "mood: warm\n"
        "intent: reply\nsalience: 0.8\n"
        "---\n"
        "intent: ignore\nsalience: 0.1\n"
    )
    reader, provider = _reader(reply)
    batch = await reader.read(
        _ctx(_msg(6, "Norman", "зонды скучные"), _msg(7, "Riker", "ну не скажи"))
    )
    assert [r.intent for r in batch.readings] == [
        ReflectiveIntent.REPLY,
        ReflectiveIntent.IGNORE,
    ]
    assert provider.messages is not None
    contents = " ".join(m["content"] for m in provider.messages)
    assert "зонды скучные" in contents
    assert "ну не скажи" in contents


def test_room_read_is_pinned_tier1() -> None:
    assert TaskType.ROOM_READ.value == "room_read"


@pytest.mark.asyncio
async def test_garbage_reply_yields_safe_all_ignore() -> None:
    # Both tiers return unparseable text; the tolerant batch parser degrades to all-IGNORE
    # of the right length rather than raising.
    api = _FakeProvider("I cannot read this room")
    local = _FakeProvider("still nothing")
    router = LLMRouter(providers={0: local, 1: api})
    reader = LlmBatchRoomReader(router=router)
    batch = await reader.read(_ctx(_msg(6, "N", "a"), _msg(7, "R", "b")))
    assert len(batch.readings) == 2
    assert all(r.intent is ReflectiveIntent.IGNORE for r in batch.readings)


@pytest.mark.asyncio
async def test_empty_burst_never_calls_the_model() -> None:
    reader, provider = _reader("mood: warm")
    batch = await reader.read(_ctx())
    assert batch.readings == ()
    assert provider.calls == 0
