# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""AgentRuntime — the GUPPI process lifecycle over a single asyncio loop.

Owns start / stop and the supervised background tasks (heartbeat, ticks). It is
transport- and provider-agnostic: collaborators arrive as callables, so the
runtime can be exercised with fakes. The composition root (``bob.app``) injects
the real background tasks and then awaits :meth:`run_until_stopped`.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

logger = logging.getLogger(__name__)

# BOB-107: per-task cap when stopping — shutdown hygiene, NOT a deadlock cure.
#
# 🔴 Its original rationale («a task stuck cancelling on an aiosqlite worker-thread
# deadlock») was WRONG: there is no such deadlock. The hang it was written against was a
# TEST defect — a poller that budgeted in event-loop turns, starved the driver's worker
# thread, and died before ever asking the runtime to stop. Measured and written up in the
# BOB-107 BRIEF. The cap survives on its own merit (a background task that refuses to
# finish cancelling must not hold up systemctl restart), not on that story.
_TASK_STOP_TIMEOUT_SECONDS = 5.0

# A supervised background coroutine factory (e.g. a heartbeat tick loop).
type BackgroundTask = Callable[[], Coroutine[Any, Any, None]]


class RuntimeState(enum.Enum):
    """Lifecycle state of the agent runtime."""

    STOPPED = "stopped"
    RUNNING = "running"


class AgentRuntime:
    """Supervise the GUPPI asyncio lifecycle and its background tasks."""

    def __init__(
        self,
        *,
        background_tasks: Sequence[BackgroundTask] | None = None,
    ) -> None:
        self._background_factories: tuple[BackgroundTask, ...] = tuple(background_tasks or ())
        self._state = RuntimeState.STOPPED
        self._tasks: list[asyncio.Task[None]] = []
        self._stopped: asyncio.Event = asyncio.Event()

    @property
    def state(self) -> RuntimeState:
        """Current lifecycle state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Whether the runtime is currently running."""
        return self._state is RuntimeState.RUNNING

    async def start(self) -> None:
        """Start the runtime and schedule background tasks (idempotent)."""
        if self._state is RuntimeState.RUNNING:
            logger.debug("start() ignored: runtime already running")
            return
        self._stopped = asyncio.Event()
        self._tasks = [asyncio.create_task(factory()) for factory in self._background_factories]
        self._state = RuntimeState.RUNNING
        logger.info("AgentRuntime started with %d background task(s)", len(self._tasks))

    async def stop(self) -> None:
        """Stop the runtime, cancelling background tasks gracefully (idempotent)."""
        if self._state is RuntimeState.STOPPED:
            logger.debug("stop() ignored: runtime already stopped")
            return
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                # BOB-107: bound the await so one uncooperative task cannot hold up the
                # whole shutdown (and therefore systemctl restart).
                #
                # 🔴 Known limitation, stated rather than papered over: a task we give up
                # on keeps RUNNING, and shutdown closes the connection right after — so an
                # abandoned task can still reach for a closing DB. That is tolerable only
                # because giving up is the degraded path and the process is on its way
                # out; it is NOT a clean drain. Making it clean means giving background
                # tasks a cooperative stop signal, which is its own piece of work.
                try:
                    await asyncio.wait_for(task, timeout=_TASK_STOP_TIMEOUT_SECONDS)
                except TimeoutError:
                    logger.warning(
                        "task did not finish cancelling in %.0fs — abandoning it; it may "
                        "still run against a closing connection (BOB-107)",
                        _TASK_STOP_TIMEOUT_SECONDS,
                    )
        self._tasks = []
        self._state = RuntimeState.STOPPED
        self._stopped.set()
        logger.info("AgentRuntime stopped")

    async def run_until_stopped(self) -> None:
        """Block until :meth:`stop` is called (the process main-loop entry)."""
        if self._state is RuntimeState.STOPPED:
            return
        await self._stopped.wait()
