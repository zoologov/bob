# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`ChatDispatcher` — the intake seam (BOB-066 Срез 2.1).

Proves the concurrency-foundation invariants structurally: ``submit`` is fast and
non-blocking; one worker per ``chat_id`` serializes a chat's messages in arrival order
(INV-5) while distinct chats run in parallel; each message is handled under its own
turn scope (INV-4); a focused message never waits (INV-1/10).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope


def _msg(chat_id: int, message_id: int, *, text: str = "привет") -> MessageReceived:
    return MessageReceived(
        update_id=message_id, chat_id=chat_id, message_id=message_id, text=text
    )


def _never_focused(_message: MessageReceived) -> bool:
    return False


class _Recorder:
    """Captures every (message, scope) the workers handle, in handling order."""

    def __init__(self) -> None:
        self.handled: list[tuple[MessageReceived, TurnScope]] = []

    async def __call__(self, message: MessageReceived, scope: TurnScope) -> None:
        self.handled.append((message, scope))


async def _drain(dispatcher: ChatDispatcher) -> None:
    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_submit_is_non_blocking() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_message: MessageReceived, _scope: TurnScope) -> None:
        started.set()
        await release.wait()

    dispatcher = ChatDispatcher(handle=slow, base_seed=1, is_focused=_never_focused)
    dispatcher.submit(_msg(1, 1))  # returns at once even though the handler blocks
    await asyncio.wait_for(started.wait(), timeout=1)  # the worker did pick it up
    assert not release.is_set()
    release.set()
    await _drain(dispatcher)


@pytest.mark.asyncio
async def test_one_chat_is_handled_in_arrival_order() -> None:
    recorder = _Recorder()
    dispatcher = ChatDispatcher(handle=recorder, base_seed=1, is_focused=_never_focused)
    for message_id in (1, 2, 3):
        dispatcher.submit(_msg(7, message_id))
    await _drain(dispatcher)
    # 🔴 INV-5: strict arrival order within the chat.
    assert [m.message_id for m, _ in recorder.handled] == [1, 2, 3]


@pytest.mark.asyncio
async def test_each_message_gets_its_own_scope_seeded_by_coordinates() -> None:
    recorder = _Recorder()
    dispatcher = ChatDispatcher(handle=recorder, base_seed=99, is_focused=_never_focused)
    dispatcher.submit(_msg(7, 1))
    dispatcher.submit(_msg(7, 2))
    await _drain(dispatcher)
    (msg_a, scope_a), (_msg_b, scope_b) = recorder.handled
    assert (scope_a.chat_id, scope_a.message_id) == (7, msg_a.message_id)
    # 🔴 INV-4: two messages of one chat draw from independent rngs (no leak between turns).
    assert scope_a.rng.random() != scope_b.rng.random()


@pytest.mark.asyncio
async def test_distinct_chats_run_on_distinct_workers() -> None:
    active = 0
    peak = 0
    gate = asyncio.Event()

    async def concurrent(_message: MessageReceived, _scope: TurnScope) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await gate.wait()
        active -= 1

    dispatcher = ChatDispatcher(handle=concurrent, base_seed=1, is_focused=_never_focused)
    dispatcher.submit(_msg(1, 1))
    dispatcher.submit(_msg(2, 1))
    await asyncio.sleep(0.05)  # let both chat workers reach the gate
    gate.set()
    await _drain(dispatcher)
    # Parallelism ACROSS chat_ids: both handlers were in flight at once.
    assert peak == 2


@pytest.mark.asyncio
async def test_a_failing_turn_is_isolated_and_the_chat_keeps_flowing() -> None:
    seen: list[int] = []

    async def flaky(message: MessageReceived, _scope: TurnScope) -> None:
        if message.message_id == 1:
            raise RuntimeError("boom")
        seen.append(message.message_id)

    dispatcher = ChatDispatcher(handle=flaky, base_seed=1, is_focused=_never_focused)
    dispatcher.submit(_msg(7, 1))
    dispatcher.submit(_msg(7, 2))
    await _drain(dispatcher)
    # The raise on message 1 does not starve the chat — message 2 is still handled.
    assert seen == [2]


@pytest.mark.asyncio
async def test_submit_after_close_is_dropped() -> None:
    recorder = _Recorder()
    dispatcher = ChatDispatcher(handle=recorder, base_seed=1, is_focused=_never_focused)
    await dispatcher.aclose()
    dispatcher.submit(_msg(7, 1))
    assert recorder.handled == []
