# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Debounce coalescing under a still-growing burst (BOB-066 Срез 2.1).

``test_inbox.py`` covers the settled cases; this fills the harder one — a message that lands
DURING the quiet window. The debounce must loop («пусть допишут»): keep waiting while the
buffer grows, then flush the whole burst as one batch once it settles. Driven with a fake
sleep that injects the mid-window arrival, so the growth loop is exercised deterministically.
"""

from __future__ import annotations

import pytest

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake.inbox import ChatInbox

_CHAT = 42


def _msg(message_id: int) -> MessageReceived:
    return MessageReceived(
        update_id=message_id, chat_id=_CHAT, message_id=message_id, text="привет"
    )


def _never_focused(_message: MessageReceived) -> bool:
    return False


@pytest.mark.asyncio
async def test_debounce_keeps_waiting_while_the_burst_is_still_growing() -> None:
    # Arrange: on the FIRST quiet window a new message lands (someone is still typing); the
    # SECOND window sees no growth and the batch settles.
    holder: dict[str, ChatInbox] = {}
    windows = 0

    async def sleep(_seconds: float) -> None:
        nonlocal windows
        windows += 1
        if windows == 1:
            holder["inbox"].offer(_msg(2))  # arrival during the window → batch must grow

    inbox = ChatInbox(quiet_window=0.0, is_focused=_never_focused, sleep=sleep)
    holder["inbox"] = inbox

    # Act.
    inbox.offer(_msg(1))
    batch = await inbox.drain_batch()

    # Assert: the mid-window arrival was coalesced, and the debounce waited a second window.
    assert [message.message_id for message in batch] == [1, 2]
    assert windows == 2
    assert inbox.empty


@pytest.mark.asyncio
async def test_debounce_loops_until_the_burst_finally_settles() -> None:
    # Arrange: the burst grows across several consecutive windows, then stops.
    holder: dict[str, ChatInbox] = {}
    windows = 0

    async def sleep(_seconds: float) -> None:
        nonlocal windows
        windows += 1
        if windows <= 3:
            holder["inbox"].offer(_msg(windows + 1))  # 2, 3, 4 land window by window

    inbox = ChatInbox(quiet_window=0.0, is_focused=_never_focused, sleep=sleep)
    holder["inbox"] = inbox

    # Act.
    inbox.offer(_msg(1))
    batch = await inbox.drain_batch()

    # Assert: every mid-window message coalesced; the loop stopped only once it settled.
    assert [message.message_id for message in batch] == [1, 2, 3, 4]
    assert windows == 4  # three growth windows + one quiet window that broke the loop
