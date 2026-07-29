# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""ChatInbox (BOB-066 Срез 2.1) — one chat's message buffer with a debounce window.

A per-``chat_id`` staging area between the fast bus subscriber and the slow worker.
:meth:`offer` is non-blocking (append + wake); :meth:`drain_batch` waits a short quiet
window — «пусть допишут» — then returns the settled burst so the worker handles a chat's
messages in arrival order. 🔴 A focused message (a direct address to Bob) short-circuits
the wait so it is never held back or collapsed by batching (INV-1/10); on graceful close the
window is skipped so shutdown drains at once. :meth:`peek_since` is a non-draining snapshot a
later staleness / catch-up step reads.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from bob.application.runtime.intake.decisions import batch_grew, should_debounce

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bob.application.runtime.events import MessageReceived

    type _Sleep = Callable[[float], Awaitable[None]]
    type _Focused = Callable[[MessageReceived], bool]


class ChatInbox:
    """One chat's buffer: non-blocking ``offer`` + debounced ``drain_batch``."""

    def __init__(
        self,
        *,
        quiet_window: float,
        is_focused: _Focused,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        self._quiet_window = quiet_window
        self._is_focused = is_focused
        self._sleep = sleep
        self._buffer: list[MessageReceived] = []
        self._arrival = asyncio.Event()
        self._closing = False

    @property
    def empty(self) -> bool:
        """Whether the buffer currently holds no messages."""
        return not self._buffer

    @property
    def closing(self) -> bool:
        """Whether the inbox has been closed for graceful drain."""
        return self._closing

    def offer(self, message: MessageReceived) -> None:
        """Buffer ``message`` and wake a waiting drain (fast, non-blocking)."""
        self._buffer.append(message)
        self._arrival.set()

    def close(self) -> None:
        """Signal graceful drain: flush without waiting and let the worker exit."""
        self._closing = True
        self._arrival.set()

    def _has_focus(self) -> bool:
        return any(self._is_focused(message) for message in self._buffer)

    async def drain_batch(self) -> list[MessageReceived]:
        """Wait the quiet window (unless focused/closing) then return + clear the burst.

        Blocks until at least one message is buffered, then — while the debounce applies —
        sleeps a quiet window and loops only if the buffer grew (someone is still typing).
        A focused message or a closing inbox flushes immediately. The snapshot + clear is
        synchronous (no ``await`` between), so a concurrent ``offer`` never loses a message.
        """
        if not self._closing:
            await self._arrival.wait()
        while should_debounce(closing=self._closing, has_focus=self._has_focus()):
            before = len(self._buffer)
            await self._sleep(self._quiet_window)
            if not batch_grew(before=before, after=len(self._buffer)):
                break
        batch = list(self._buffer)
        self._buffer.clear()
        self._arrival.clear()
        return batch

    def peek_since(self, after_update_id: int) -> tuple[MessageReceived, ...]:
        """A non-draining snapshot of buffered messages newer than ``after_update_id``.

        A read-only hook for a later staleness / catch-up step (Фаза 3): it inspects what
        has piled up behind the current turn without consuming it, so the buffer keeps
        feeding the normal drain.
        """
        return tuple(
            message for message in self._buffer if message.update_id > after_update_id
        )
