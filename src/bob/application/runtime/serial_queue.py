# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""SerialQueue — hand work to ONE background worker so the caller never waits on it.

One responsibility: accept an item at once and handle it later, strictly in arrival order
and one at a time. It is for a slow handler behind a caller that must not stall: the bus
subscriber for reactions is called straight from the Telegram poll loop (BOB-126, review
M1 — the reaction judge is a Tier-0 call that, on the understudy, may think up to 180 s,
and while it thought no ``get_updates`` went out for either bot).

Guarantees:

* **order and one-at-a-time** — one worker, FIFO: item N+1 starts after N has finished. A
  handler that reads and writes the same state across an ``await`` (load a relationship →
  ask the judge → save it) does not lose a neighbour's update — exactly as when the poller
  itself waited on it;
* **a failing handler does not kill the worker** — the exception is logged with its stack
  and the next item is handled;
* **the caller waits on nothing** — :meth:`submit` is synchronous and returns at once.

What it does not give, named: an item lives in process memory. The poller advances its
offset as soon as :meth:`submit` returns, so an item accepted and not yet handled when the
process dies is lost (at-most-once) — as a message is in
:class:`~bob.application.runtime.intake.dispatcher.ChatDispatcher`. :meth:`aclose` does
not wait on a slow handler: a service stop is bounded by ``TimeoutStopSec``, so the item in
flight is cancelled, the queue is dropped and the number dropped is logged. Fit only for
work that may be lost — reaction perception is decorative.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["SerialQueue"]

logger = logging.getLogger(__name__)


class SerialQueue[T]:
    """A FIFO drained by one background worker; :meth:`submit` never blocks."""

    def __init__(self, handle: Callable[[T], Awaitable[None]], *, name: str) -> None:
        self._handle = handle
        self._name = name
        self._items: deque[T] = deque()
        self._wakeup = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._in_flight = False
        self._closing = False
        self._worker: asyncio.Task[None] | None = None

    def submit(self, item: T) -> None:
        """Queue ``item`` and return at once; after :meth:`aclose` it is dropped."""
        if self._closing:
            return
        self._items.append(item)
        self._idle.clear()
        self._wakeup.set()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work(), name=f"serial-queue:{self._name}")

    async def wait_for_idle(self) -> None:
        """Wait until the queue is empty and nothing is in flight (a test seam)."""
        await self._idle.wait()

    async def aclose(self) -> None:
        """Stop accepting, cancel the item in flight, drop the rest — without waiting."""
        self._closing = True
        dropped = len(self._items) + (1 if self._in_flight else 0)
        self._items.clear()
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._in_flight = False
        self._idle.set()
        if dropped:
            logger.info("%s: при остановке брошено необработанных: %d", self._name, dropped)

    async def _work(self) -> None:
        while True:
            if not self._items:
                self._idle.set()
                self._wakeup.clear()
                await self._wakeup.wait()
                continue
            item = self._items.popleft()
            self._in_flight = True
            try:
                await self._handle(item)
            except Exception:
                logger.exception("%s: обработчик упал — элемент брошен", self._name)
            finally:
                self._in_flight = False
