# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""ChatDispatcher (BOB-066 Срез 2.1) — the intake seam: fast submit, per-chat workers.

The bus subscriber for an inbound message becomes :meth:`submit` — normalise → buffer →
return — so the Telegram poller never blocks on Bob's generation again. Behind it, one
worker task per ``chat_id`` drains that chat's :class:`ChatInbox` and runs the real
handler sequentially:

* 🔴 INV-5 (order/serialization): a single worker owns a chat's inbox, so that chat's
  messages are handled strictly in arrival order (floor / mood / relationship advance in
  order). Parallelism is only ACROSS chats (distinct workers) — no global lock, so a
  worker can only ever wait on its own inbox and can never deadlock another.
* 🔴 INV-4 (turn-local isolation): each message is handled under a fresh
  :class:`~bob.application.runtime.intake.scope.TurnScope`, so its seeded draws never leak
  into the next message.

Graceful :meth:`aclose` closes every inbox and awaits the workers, so a drained shutdown
delivers the buffered replies (the acceptance/e2e harness relies on this).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from bob.application.runtime.intake.inbox import ChatInbox
from bob.application.runtime.intake.scope import new_turn_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bob.application.runtime.events import MessageReceived
    from bob.application.runtime.intake.scope import TurnScope

    type _Handle = Callable[[MessageReceived, TurnScope], Awaitable[None]]
    type _Sleep = Callable[[float], Awaitable[None]]
    type _Focused = Callable[[MessageReceived], bool]

logger = logging.getLogger(__name__)


class ChatDispatcher:
    """Route inbound messages to per-``chat_id`` workers that serialize each chat."""

    def __init__(
        self,
        *,
        handle: _Handle,
        base_seed: int,
        is_focused: _Focused,
        quiet_window: float = 0.0,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        self._handle = handle
        self._base_seed = base_seed
        self._is_focused = is_focused
        self._quiet_window = quiet_window
        self._sleep = sleep
        self._inboxes: dict[int, ChatInbox] = {}
        self._workers: dict[int, asyncio.Task[None]] = {}
        self._closing = False
        self._pending = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def submit(self, message: MessageReceived) -> None:
        """Buffer ``message`` for its chat and ensure a worker is draining it (non-blocking).

        The fast bus subscriber: it returns at once so the poller is never blocked on Bob's
        generation. A message that arrives after :meth:`aclose` is dropped (shutting down).
        """
        if self._closing:
            return
        self._pending += 1
        self._idle.clear()
        inbox = self._inbox_for(message.chat_id)
        inbox.offer(message)
        self._ensure_worker(message.chat_id, inbox)

    async def wait_for_idle(self) -> None:
        """Block until every submitted message has been handled (no in-flight turn).

        A synchronisation seam for callers that need the turn(s) completed — the tests drive
        one message and await this before asserting the reply. Production never calls it: the
        whole point of the seam is that submit returns without waiting.
        """
        await self._idle.wait()

    def _inbox_for(self, chat_id: int) -> ChatInbox:
        inbox = self._inboxes.get(chat_id)
        if inbox is None:
            inbox = ChatInbox(
                quiet_window=self._quiet_window,
                is_focused=self._is_focused,
                sleep=self._sleep,
            )
            self._inboxes[chat_id] = inbox
        return inbox

    def _ensure_worker(self, chat_id: int, inbox: ChatInbox) -> None:
        task = self._workers.get(chat_id)
        if task is None or task.done():
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id, inbox))

    async def _worker(self, chat_id: int, inbox: ChatInbox) -> None:
        """Drain one chat's inbox, handling each message sequentially under its own scope."""
        while True:
            batch = await inbox.drain_batch()
            # An empty batch only ever comes back once the inbox is closing (a live inbox
            # blocks the drain until a message arrives), so it is the worker's exit signal.
            if not batch:
                return
            for message in batch:
                await self._handle_one(chat_id, message)

    async def _handle_one(self, chat_id: int, message: MessageReceived) -> None:
        """Run the real handler for one message under a fresh turn scope, isolating faults."""
        scope = new_turn_scope(
            base_seed=self._base_seed,
            chat_id=message.chat_id,
            message_id=message.message_id,
        )
        try:
            await self._handle(message, scope)
        except Exception:
            logger.exception("intake worker failed handling a message for chat %s", chat_id)
        finally:
            self._pending -= 1
            if self._pending == 0:
                self._idle.set()

    async def aclose(self) -> None:
        """Gracefully drain: stop accepting, flush every inbox, await the workers."""
        self._closing = True
        for inbox in self._inboxes.values():
            inbox.close()
        workers = list(self._workers.values())
        self._workers.clear()
        for task in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
