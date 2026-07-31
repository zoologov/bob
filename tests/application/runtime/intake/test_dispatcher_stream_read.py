# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Holistic stream-read врезка into :class:`ChatDispatcher._handle_batch` (BOB-072).

The pure batch read + verdict projection are tested in the domain/application units; here we
assert the DISPATCHER wires them into the hot path:

* OFF (no ambient reader injected) → the settled burst takes the current per-message top-k
  path, no message carries a batch reading — byte-identical to before the врезка;
* ON → the burst is SPLIT: focal (direct address) messages are handled deterministically as
  now (INV-1, no batch reading stamped), and the WHOLE ambient part goes through ONE batch
  read whose per-message reading rides each ambient message's scope;
* 🔴 every ambient message is still handled (persist + floor for all — INV-S2), so
  ``wait_for_idle`` resolves and the pending counter reaches zero.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher
from bob.conversation.addressivity import ResponseOutcome
from bob.conversation.room_reading import ReflectiveIntent, RoomMood, RoomReading

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.runtime.intake.scope import TurnScope


def _msg(message_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=7,
        message_id=message_id,
        text=f"m{message_id}",
        sender_id=message_id,
        sender_name=f"u{message_id}",
        mentions_bob=mentions_bob,
    )


def _focus_on_mention(message: MessageReceived) -> bool:
    return message.mentions_bob


def _reading(message_id: int) -> RoomReading:
    return RoomReading(
        situation=f"r{message_id}",
        pairings=(),
        room_mood=RoomMood.WARM,
        intent=ReflectiveIntent.REPLY,
        addressee_id=None,
        salience=0.9,
        emoji=None,
        wants_web=False,
        reason="r",
    )


class _FakeAmbientReader:
    """Records the ambient bursts it read; returns one reading per message (by message_id)."""

    def __init__(self) -> None:
        self.bursts: list[list[int]] = []

    async def read(self, messages: Sequence[MessageReceived]) -> Sequence[RoomReading]:
        self.bursts.append([m.message_id for m in messages])
        return [_reading(m.message_id) for m in messages]


async def _drive(
    *,
    ambient_reader: _FakeAmbientReader | None,
    messages: list[MessageReceived],
) -> list[tuple[int, RoomReading | None]]:
    """Return each handled (message_id, scope.ambient_reading) in handling order."""
    seen: list[tuple[int, RoomReading | None]] = []

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        seen.append((message.message_id, scope.ambient_reading))

    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=_focus_on_mention,
        ambient_batch=ambient_reader,
    )
    for message in messages:
        dispatcher.submit(message)
    await dispatcher.aclose()
    return seen


@pytest.mark.asyncio
async def test_off_takes_the_current_path_with_no_batch_reading() -> None:
    # 🔴 Regression pin: no ambient reader → every message handled with NO batch reading.
    seen = await _drive(ambient_reader=None, messages=[_msg(1), _msg(2), _msg(3)])

    assert [message_id for message_id, _ in seen] == [1, 2, 3]
    assert all(reading is None for _, reading in seen)


@pytest.mark.asyncio
async def test_on_reads_the_whole_ambient_burst_once_and_stamps_each_reading() -> None:
    reader = _FakeAmbientReader()
    seen = await _drive(ambient_reader=reader, messages=[_msg(1), _msg(2), _msg(3)])

    # ONE holistic read over the whole ambient burst (never one read per message).
    assert reader.bursts == [[1, 2, 3]]
    # Each ambient message carries its own per-message reading.
    assert {
        message_id: (reading.situation if reading else None) for message_id, reading in seen
    } == {
        1: "r1",
        2: "r2",
        3: "r3",
    }


@pytest.mark.asyncio
async def test_on_splits_focal_out_of_the_batch_and_answers_it_deterministically() -> None:
    # 🔴 INV-1: the direct address is NOT sent to the batch reader and carries no batch reading
    # (it takes the deterministic focal path); only the ambient ones are read.
    reader = _FakeAmbientReader()
    seen = await _drive(
        ambient_reader=reader,
        messages=[_msg(1), _msg(2, mentions_bob=True), _msg(3)],
    )

    assert reader.bursts == [[1, 3]]  # the focal message (2) is excluded from the read
    by_id = dict(seen)
    assert by_id[2] is None  # focal → deterministic, no batch reading
    assert by_id[1] is not None
    assert by_id[3] is not None
    # Every message was handled (persist/floor for all → pending reaches zero).
    assert sorted(message_id for message_id, _ in seen) == [1, 2, 3]


@pytest.mark.asyncio
async def test_on_with_an_all_focal_burst_never_reads() -> None:
    reader = _FakeAmbientReader()
    seen = await _drive(
        ambient_reader=reader,
        messages=[_msg(1, mentions_bob=True), _msg(2, mentions_bob=True)],
    )

    assert reader.bursts == []  # no ambient → no read
    assert all(reading is None for _, reading in seen)


@pytest.mark.asyncio
async def test_off_and_on_are_uncapped_engage_ceiling() -> None:
    # The stream-read врезка replaces the series top-k, so ambient messages keep an uncapped
    # ENGAGE ceiling (the per-message verdict now comes from the batch reading, not a ceiling).
    ceilings: list[ResponseOutcome] = []

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        ceilings.append(scope.series_ceiling)

    reader = _FakeAmbientReader()
    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=_focus_on_mention,
        ambient_batch=reader,
    )
    dispatcher.submit(_msg(1))
    dispatcher.submit(_msg(2))
    await dispatcher.aclose()

    assert ceilings == [ResponseOutcome.ENGAGE, ResponseOutcome.ENGAGE]
