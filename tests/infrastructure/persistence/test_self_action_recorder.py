# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the self-action recorder adapters (BOB-079.1).

The memory-backed recorder renders a :class:`SelfAction` first-person and writes
one ``self_action`` :class:`EpisodicEvent` through the typed door; the no-op
recorder (the OFF-flag realisation) writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.memory.adapters.self_action_recorder import (
    MemoryBackedSelfActionRecorder,
    NoOpSelfActionRecorder,
)
from bob.memory.self_action import SelfAction, SelfActionKind

if TYPE_CHECKING:
    from bob.memory.entities import EpisodicEvent


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _SpyEpisodeStore:
    def __init__(self) -> None:
        self.saved: list[EpisodicEvent] = []

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        self.saved.append(event)


def _moment() -> datetime:
    return datetime(2026, 8, 1, 9, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_records_first_person_self_action_episode() -> None:
    store = _SpyEpisodeStore()
    recorder = MemoryBackedSelfActionRecorder(store, clock=_FixedClock(_moment()))

    await recorder.record(
        SelfAction(kind=SelfActionKind.CODING_FINISHED, target="BOB-079"),
        sender_id=42,
        visibility="owner_private",
    )

    assert len(store.saved) == 1
    event = store.saved[0]
    assert event.event_type == "self_action"
    assert event.content == "я доделал «BOB-079», открыл PR"
    assert event.tags == ("self", "coding")
    assert event.sender_id == 42
    assert event.visibility == "owner_private"
    assert event.mood_snapshot is None
    assert event.ts == _moment()


@pytest.mark.asyncio
async def test_records_anomaly_with_tag() -> None:
    store = _SpyEpisodeStore()
    recorder = MemoryBackedSelfActionRecorder(store, clock=_FixedClock(_moment()))

    await recorder.record(
        SelfAction(kind=SelfActionKind.CODING_RUNAWAY, target="BOB-079")
    )

    event = store.saved[0]
    assert "anomaly" in event.tags
    assert event.sender_id is None
    assert event.visibility is None


@pytest.mark.asyncio
async def test_noop_recorder_writes_nothing() -> None:
    store = _SpyEpisodeStore()
    recorder = NoOpSelfActionRecorder()

    await recorder.record(
        SelfAction(kind=SelfActionKind.TOOL_FAILURE, target="read_code"),
        sender_id=7,
        visibility="public",
    )

    assert store.saved == []
