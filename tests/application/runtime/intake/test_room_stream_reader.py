# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""RoomStreamReader (BOB-072) — a settled ambient burst → one per-message reading.

The application-side of the holistic stream-read врезка: it folds a settled ambient burst
of :class:`MessageReceived` into a :class:`BatchRoomReadingContext` (attributed stream +
Bob's tone), runs the ONE injected :class:`BatchRoomReader` (a single Tier-1 read) and
returns exactly one :class:`RoomReading` per message IN ARRIVAL ORDER. 🔴 A reader failure
never propagates: it degrades to a safe all-IGNORE plan of the right length so the intake
worker still persists every ambient message (INV-S2), never Bob acting on a guessed read.
"""

from __future__ import annotations

import pytest

from bob.application.runtime.intake.room_stream_reader import RoomStreamReader
from bob.conversation.room_reading import (
    BatchAmbientMessage,
    BatchRoomReading,
    BatchRoomReadingContext,
    ReflectiveIntent,
    RoomMood,
    RoomReading,
)
from bob.kernel.events import MessageReceived
from bob.social.interlocutor import InterlocutorKind


def _msg(
    message_id: int, *, text: str = "привет", sender_id: int = 5, name: str | None = "Sam"
) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=7,
        message_id=message_id,
        text=text,
        sender_id=sender_id,
        sender_name=name,
    )


def _reading(intent: ReflectiveIntent, salience: float) -> RoomReading:
    return RoomReading(
        situation="s",
        pairings=(),
        room_mood=RoomMood.WARM,
        intent=intent,
        addressee_id=None,
        salience=salience,
        emoji=None,
        wants_web=False,
        reason="r",
    )


class _RecordingReader:
    """Captures the batch context it was handed + returns a scripted per-message plan."""

    def __init__(self, plan: tuple[RoomReading, ...]) -> None:
        self._plan = plan
        self.contexts: list[BatchRoomReadingContext] = []

    async def read(self, batch_ctx: BatchRoomReadingContext) -> BatchRoomReading:
        self.contexts.append(batch_ctx)
        return BatchRoomReading(readings=self._plan, room_mood=RoomMood.WARM, reason="")


class _ExplodingReader:
    async def read(self, batch_ctx: BatchRoomReadingContext) -> BatchRoomReading:
        raise RuntimeError("router down")


@pytest.mark.asyncio
async def test_folds_the_burst_into_an_attributed_context() -> None:
    reader = _RecordingReader(
        (_reading(ReflectiveIntent.REPLY, 0.9), _reading(ReflectiveIntent.IGNORE, 0.0))
    )
    stream = RoomStreamReader(reader=reader, mood_tone=lambda: "тёплый")
    await stream.read(
        [_msg(1, text="эй", name="Sam"), _msg(2, text="ага", sender_id=8, name="Deb")]
    )

    assert len(reader.contexts) == 1
    ctx = reader.contexts[0]
    assert ctx.mood_tone == "тёплый"
    assert ctx.others_present is True
    assert isinstance(ctx.messages[0], BatchAmbientMessage)
    assert [(m.sender_id, m.sender_name, m.text) for m in ctx.messages] == [
        (5, "Sam", "эй"),
        (8, "Deb", "ага"),
    ]
    # Arrival order is stamped monotonically so the read can reason about sequence.
    assert ctx.messages[0].ts < ctx.messages[1].ts


@pytest.mark.asyncio
async def test_folds_the_perceived_kind_into_each_batch_message() -> None:
    # 🔴 BOB-078 B: with a kind resolver wired, every ambient message carries its author's
    # social kind so the read weighs a guest's warm reply as salient (не игнорит гостя).
    reader = _RecordingReader((_reading(ReflectiveIntent.IGNORE, 0.0),) * 2)

    async def perceive_kind(message: MessageReceived) -> InterlocutorKind:
        return InterlocutorKind.GUEST if message.sender_id == 8 else InterlocutorKind.OWNER

    stream = RoomStreamReader(
        reader=reader, mood_tone=lambda: "t", perceive_kind=perceive_kind
    )
    await stream.read([_msg(1, sender_id=5), _msg(2, sender_id=8)])

    kinds = [m.kind for m in reader.contexts[0].messages]
    assert kinds == [InterlocutorKind.OWNER, InterlocutorKind.GUEST]


@pytest.mark.asyncio
async def test_kind_is_none_without_a_resolver() -> None:
    # Unwired (baseline) → kind None, byte-identical to before (no marker rendered).
    reader = _RecordingReader((_reading(ReflectiveIntent.IGNORE, 0.0),))
    stream = RoomStreamReader(reader=reader, mood_tone=lambda: "t")
    await stream.read([_msg(1)])

    assert reader.contexts[0].messages[0].kind is None


@pytest.mark.asyncio
async def test_returns_one_reading_per_message_in_order() -> None:
    plan = (_reading(ReflectiveIntent.REPLY, 0.9), _reading(ReflectiveIntent.REACT, 0.8))
    stream = RoomStreamReader(reader=_RecordingReader(plan), mood_tone=lambda: "t")
    readings = await stream.read([_msg(1), _msg(2)])

    assert list(readings) == list(plan)


@pytest.mark.asyncio
async def test_reader_failure_degrades_to_a_safe_all_ignore_plan() -> None:
    # 🔴 Fallback: a router/model error yields exactly-N silent IGNORE readings (never raises),
    # so the intake worker still persists every ambient message (INV-S2).
    stream = RoomStreamReader(reader=_ExplodingReader(), mood_tone=lambda: "t")
    readings = await stream.read([_msg(1), _msg(2), _msg(3)])

    assert len(readings) == 3
    for reading in readings:
        assert reading.intent is ReflectiveIntent.IGNORE
        assert reading.salience == 0.0


@pytest.mark.asyncio
async def test_empty_burst_returns_no_readings_without_reading() -> None:
    class _NeverReader:
        async def read(self, batch_ctx: BatchRoomReadingContext) -> BatchRoomReading:
            raise AssertionError("must not read an empty burst")

    stream = RoomStreamReader(reader=_NeverReader(), mood_tone=lambda: "t")
    assert list(await stream.read([])) == []


@pytest.mark.asyncio
async def test_short_plan_is_padded_to_the_message_count() -> None:
    # A reader that returns fewer readings than messages (a contract breach) is defended: the
    # missing tail is padded with silent IGNOREs so persist-for-all still holds.
    stream = RoomStreamReader(
        reader=_RecordingReader((_reading(ReflectiveIntent.REPLY, 0.9),)),
        mood_tone=lambda: "t",
    )
    readings = await stream.read([_msg(1), _msg(2)])

    assert len(readings) == 2
    assert readings[1].intent is ReflectiveIntent.IGNORE
