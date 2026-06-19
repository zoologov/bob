# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""periodic — wrap a tick coroutine into a supervised, repeating background loop.

The :class:`~bob.application.runtime.agent.AgentRuntime` takes background tasks as
zero-arg coroutine factories. The heartbeat ticks
(:mod:`bob.application.usecases.heartbeat`) are *one-shot* coroutines, so this
helper turns a tick into the periodic loop the runtime supervises: run the tick,
sleep, repeat. A tick that raises is logged and isolated so one bad iteration can
never kill the heartbeat; cancellation (on runtime stop) propagates cleanly.

Sleeping is injected so the loop is deterministic in tests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

logger = logging.getLogger(__name__)

# A one-shot tick: do a unit of work, then return.
type Tick = Callable[[], Awaitable[None]]

# An async sleep seam (defaults to asyncio.sleep), injectable for tests.
type Sleep = Callable[[float], Awaitable[None]]


def periodic(
    tick: Tick,
    *,
    interval_seconds: float,
    sleep: Sleep | None = None,
) -> Callable[[], Coroutine[object, object, None]]:
    """Return a runtime background factory that runs ``tick`` every interval.

    The returned coroutine factory loops forever: invoke ``tick``, isolate any
    error it raises, then sleep ``interval_seconds``. It exits only on
    cancellation (which the runtime issues on stop).
    """
    _sleep: Sleep = sleep if sleep is not None else asyncio.sleep

    async def loop() -> None:
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("heartbeat tick failed; continuing")
            await _sleep(interval_seconds)

    return loop
