# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`ChatInbox` — the per-chat buffer + debounce (BOB-066 Срез 2.1)."""

from __future__ import annotations

import pytest

from bob.application.runtime.intake.inbox import ChatInbox
from bob.kernel.events import MessageReceived

_CHAT = 42


def _msg(
    message_id: int, *, text: str = "привет", update_id: int | None = None
) -> MessageReceived:
    return MessageReceived(
        update_id=message_id if update_id is None else update_id,
        chat_id=_CHAT,
        message_id=message_id,
        text=text,
    )


def _never_focused(_message: MessageReceived) -> bool:
    return False


class _RecordingSleep:
    """A fake sleep that records how many quiet windows were awaited."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _seconds: float) -> None:
        self.calls += 1


@pytest.mark.asyncio
async def test_drain_returns_a_settled_single_message() -> None:
    sleep = _RecordingSleep()
    inbox = ChatInbox(quiet_window=0.01, is_focused=_never_focused, sleep=sleep)
    inbox.offer(_msg(1))
    batch = await inbox.drain_batch()
    assert [m.message_id for m in batch] == [1]
    assert inbox.empty
    # Ambient message → one quiet window was awaited (debounce applied).
    assert sleep.calls == 1


@pytest.mark.asyncio
async def test_drain_coalesces_an_already_queued_burst() -> None:
    inbox = ChatInbox(quiet_window=0.0, is_focused=_never_focused)
    inbox.offer(_msg(1))
    inbox.offer(_msg(2))
    inbox.offer(_msg(3))
    batch = await inbox.drain_batch()
    # 🔴 The burst is returned together, in arrival order.
    assert [m.message_id for m in batch] == [1, 2, 3]


@pytest.mark.asyncio
async def test_focused_message_skips_the_quiet_window() -> None:
    sleep = _RecordingSleep()

    def focus_on_two(message: MessageReceived) -> bool:
        return message.message_id == 2

    inbox = ChatInbox(quiet_window=99.0, is_focused=focus_on_two, sleep=sleep)
    inbox.offer(_msg(1))
    inbox.offer(_msg(2, text="Боб, ответь"))
    # 🔴 INV-1/10: a focused message in the buffer flushes at once — the 99s window is
    # never awaited, so a focus signal cannot be dropped or delayed by batching.
    batch = await inbox.drain_batch()
    assert [m.message_id for m in batch] == [1, 2]
    assert sleep.calls == 0


@pytest.mark.asyncio
async def test_close_flushes_without_waiting() -> None:
    sleep = _RecordingSleep()
    inbox = ChatInbox(quiet_window=99.0, is_focused=_never_focused, sleep=sleep)
    inbox.offer(_msg(1))
    inbox.close()
    batch = await inbox.drain_batch()
    assert [m.message_id for m in batch] == [1]
    assert sleep.calls == 0
    assert inbox.closing


@pytest.mark.asyncio
async def test_peek_since_is_non_draining() -> None:
    inbox = ChatInbox(quiet_window=0.0, is_focused=_never_focused)
    inbox.offer(_msg(1, update_id=10))
    inbox.offer(_msg(2, update_id=11))
    snapshot = inbox.peek_since(10)
    assert [m.update_id for m in snapshot] == [11]
    # Peeking does not consume — the drain still sees both.
    batch = await inbox.drain_batch()
    assert [m.message_id for m in batch] == [1, 2]
