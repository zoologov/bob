# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Concurrency stress tests for :class:`ChatDispatcher` (BOB-066 Срез 2.1).

The decision core is truth-tabled elsewhere; this module hammers the invariants a pure
unit test cannot reach — the ones that only exist because real turns run as concurrent
asyncio tasks:

* 🔴 INV-5 (serialization): two messages of the SAME ``chat_id`` are never inside the
  handler at once. Proven with an enter/exit-instrumented handler that yields control while
  "inside" ``handle`` — if a second turn slipped in, the recorded timeline would nest and
  the live-concurrency peak would exceed 1. Also proven under the REAL race: a later message
  submitted while turn-1 is still generating must wait behind it.
* Cross-chat parallelism: messages of DIFFERENT chats DO run concurrently. Proven
  deterministically with an :class:`asyncio.Barrier` that only trips once both chats are
  inside the handler — a global lock would deadlock it (never a wall-clock sleep).
* 🔴 INV-1/10 (focus flushes the debounce): a focused message is handled without awaiting
  the quiet window even when the window is effectively infinite, tested at the dispatcher /
  batch level (not just the pure focus predicate).
* Idle accounting: ``wait_for_idle`` returns only once every submitted turn is done —
  including a turn that raised — and re-arms across bursts.

The tests use asyncio events / barriers rather than sleeps so they are deterministic.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.dispatcher import ChatDispatcher

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bob.application.runtime.intake.scope import TurnScope


def _msg(chat_id: int, message_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=chat_id,
        message_id=message_id,
        text="привет",
        mentions_bob=mentions_bob,
    )


def _never_focused(_message: MessageReceived) -> bool:
    return False


async def _yield_loop(times: int = 20) -> None:
    """Hand control to the event loop repeatedly so pending workers run to a blocking point.

    Deterministic stand-in for "let the (possibly buggy, eager) workers make all the progress
    they can" — after this returns, anything that *could* have been handled has been.
    """
    for _ in range(times):
        await asyncio.sleep(0)


class _ControlledSleep:
    """A quiet-window sleep that blocks until explicitly resumed (models an unfinished window)."""

    def __init__(self) -> None:
        self.calls = 0
        self._resume = asyncio.Event()

    async def __call__(self, _seconds: float) -> None:
        self.calls += 1
        await self._resume.wait()

    def resume(self) -> None:
        self._resume.set()


@pytest.mark.asyncio
async def test_same_chat_never_has_two_handlers_in_flight() -> None:
    # Arrange: a handler that yields control several times while "inside" handle, so an
    # overlapping second turn of the same chat would be observable.
    active = 0
    peak = 0
    timeline: list[tuple[str, int]] = []

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        timeline.append(("enter", message.message_id))
        await _yield_loop(5)  # give any concurrent turn of this chat a chance to interleave
        timeline.append(("exit", message.message_id))
        active -= 1

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act: three messages of ONE chat.
    for message_id in (1, 2, 3):
        dispatcher.submit(_msg(7, message_id))
    await dispatcher.aclose()

    # Assert: 🔴 INV-5 — strictly serialized, never nested, never two at once.
    assert peak == 1
    assert timeline == [
        ("enter", 1),
        ("exit", 1),
        ("enter", 2),
        ("exit", 2),
        ("enter", 3),
        ("exit", 3),
    ]


@pytest.mark.asyncio
async def test_message_arriving_mid_generation_waits_behind_the_in_flight_turn() -> None:
    # Arrange: turn 1 blocks (Bob is still "generating") until we release it.
    entered: list[int] = []
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        entered.append(message.message_id)
        if message.message_id == 1:
            first_entered.set()
            await release_first.wait()

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act: submit turn 1, wait until it is genuinely in-flight, THEN submit 2 and 3.
    dispatcher.submit(_msg(4, 1))
    await asyncio.wait_for(first_entered.wait(), timeout=1)
    dispatcher.submit(_msg(4, 2))
    dispatcher.submit(_msg(4, 3))
    await _yield_loop()  # an eager worker would (wrongly) start turn 2 here

    # Assert: 🔴 INV-5 — 2 and 3 are still buffered behind the in-flight turn 1.
    assert entered == [1]

    # Release and drain: order is preserved.
    release_first.set()
    await dispatcher.aclose()
    assert entered == [1, 2, 3]


@pytest.mark.asyncio
async def test_distinct_chats_run_concurrently_no_global_lock() -> None:
    # Arrange: a barrier that only releases once BOTH chats are inside the handler. A global
    # lock around handling would let only one in at a time → the barrier deadlocks.
    barrier = asyncio.Barrier(2)
    released: list[int] = []

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        # If handling were globally serialized this wait never completes (only one party
        # can ever be here) — the deadlock surfaces as an empty ``released``.
        await asyncio.wait_for(barrier.wait(), timeout=1)
        released.append(message.chat_id)

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act: one message each in two distinct chats.
    dispatcher.submit(_msg(1, 1))
    dispatcher.submit(_msg(2, 1))
    await dispatcher.aclose()

    # Assert: both chats reached the barrier at once → genuine cross-chat parallelism.
    assert sorted(released) == [1, 2]


@pytest.mark.asyncio
async def test_many_chats_do_not_serialize_behind_one_slow_chat() -> None:
    # Arrange: chat 1 is stuck generating; other chats must still make progress (their own
    # workers), proving no accidental head-of-line blocking across chats.
    handled: list[int] = []
    stuck = asyncio.Event()
    slow_entered = asyncio.Event()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        if message.chat_id == 1:
            slow_entered.set()
            await stuck.wait()
            return
        handled.append(message.chat_id)

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act: a slow chat, then three fast independent chats.
    dispatcher.submit(_msg(1, 1))
    await asyncio.wait_for(slow_entered.wait(), timeout=1)
    for chat_id in (2, 3, 4):
        dispatcher.submit(_msg(chat_id, 1))
    await _yield_loop()

    # Assert: the fast chats were served while chat 1 is still blocked.
    assert sorted(handled) == [2, 3, 4]

    stuck.set()
    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_focused_message_is_handled_without_awaiting_the_quiet_window() -> None:
    # Arrange: an effectively infinite quiet window; a message that reads focused must bypass
    # it entirely (INV-1/10) — tested through the dispatcher, not the pure predicate.
    handled: list[int] = []
    sleep = _ControlledSleep()

    def focus_on_mention(message: MessageReceived) -> bool:
        return message.mentions_bob

    dispatcher = ChatDispatcher(
        handle=_appender(handled),
        base_seed=1,
        is_focused=focus_on_mention,
        quiet_window=999.0,
        sleep=sleep,
    )

    # Act: a focused message alone.
    dispatcher.submit(_msg(7, 1, mentions_bob=True))
    await asyncio.wait_for(_until(lambda: handled == [1]), timeout=1)

    # Assert: 🔴 INV-1/10 — handled at once, the quiet window was never even entered.
    assert sleep.calls == 0

    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_ambient_message_waits_on_the_quiet_window() -> None:
    # Arrange: the counterpart — a NON-focused message is held in the (blocking) quiet window.
    handled: list[int] = []
    sleep = _ControlledSleep()

    dispatcher = ChatDispatcher(
        handle=_appender(handled),
        base_seed=1,
        is_focused=_never_focused,
        quiet_window=999.0,
        sleep=sleep,
    )

    # Act: an ambient message; let the worker run to its blocking point.
    dispatcher.submit(_msg(7, 1))
    await _yield_loop()

    # Assert: still buffered inside the debounce window (not yet handled).
    assert handled == []
    assert sleep.calls == 1

    # Release the window and drain: it settles into a single batch.
    sleep.resume()
    await dispatcher.aclose()
    assert handled == [1]


@pytest.mark.asyncio
async def test_focused_message_flushes_a_growing_ambient_burst_at_once() -> None:
    # Arrange: ambient chatter would sit in the window; a focused message in the same burst
    # must flush the WHOLE batch immediately (nothing dropped, nothing delayed).
    handled: list[int] = []
    sleep = _ControlledSleep()

    def focus_on_mention(message: MessageReceived) -> bool:
        return message.mentions_bob

    dispatcher = ChatDispatcher(
        handle=_appender(handled),
        base_seed=1,
        is_focused=focus_on_mention,
        quiet_window=999.0,
        sleep=sleep,
    )

    # Act: two ambient + one focused, all in one chat, submitted together.
    dispatcher.submit(_msg(7, 1))
    dispatcher.submit(_msg(7, 2))
    dispatcher.submit(_msg(7, 3, mentions_bob=True))
    await asyncio.wait_for(_until(lambda: len(handled) == 3), timeout=1)

    # Assert: the burst flushed at once, in order, without awaiting the window.
    assert handled == [1, 2, 3]
    assert sleep.calls == 0

    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_wait_for_idle_returns_immediately_when_there_is_no_work() -> None:
    dispatcher = ChatDispatcher(
        handle=_appender([]), base_seed=1, is_focused=_never_focused
    )
    # Idle from the start → returns at once (covers the idle-already-set path).
    await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=1)
    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_wait_for_idle_blocks_until_every_turn_including_a_failing_one_is_done() -> None:
    # Arrange: turn 2 raises; idle accounting must still settle (the finally decrements).
    handled: list[int] = []
    gate = asyncio.Event()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        await gate.wait()
        if message.message_id == 2:
            raise RuntimeError("boom")
        handled.append(message.message_id)

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act: three turns across two chats; wait_for_idle must not resolve while work is pending.
    dispatcher.submit(_msg(7, 1))
    dispatcher.submit(_msg(7, 2))
    dispatcher.submit(_msg(9, 3))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=0.05)

    gate.set()
    await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=1)

    # Assert: idle settled despite the raised turn; the non-failing turns completed.
    assert sorted(handled) == [1, 3]
    await dispatcher.aclose()


@pytest.mark.asyncio
async def test_wait_for_idle_re_arms_across_successive_bursts() -> None:
    # Arrange.
    handled: list[int] = []
    gate = asyncio.Event()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        await gate.wait()
        handled.append(message.message_id)

    dispatcher = ChatDispatcher(handle=handle, base_seed=1, is_focused=_never_focused)

    # Act 1: first burst settles.
    gate.set()
    dispatcher.submit(_msg(7, 1))
    await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=1)
    assert handled == [1]

    # Act 2: a fresh submit clears idle again — wait_for_idle must block anew.
    gate.clear()
    dispatcher.submit(_msg(7, 2))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=0.05)
    gate.set()
    await asyncio.wait_for(dispatcher.wait_for_idle(), timeout=1)

    # Assert.
    assert handled == [1, 2]
    await dispatcher.aclose()


def _appender(
    sink: list[int],
) -> Callable[[MessageReceived, TurnScope], Awaitable[None]]:
    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        sink.append(message.message_id)

    return handle


async def _until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0)
