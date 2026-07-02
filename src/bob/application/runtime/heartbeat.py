# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""periodic — wrap a tick coroutine into a supervised, repeating background loop.

The :class:`~bob.application.runtime.agent.AgentRuntime` takes background tasks as
zero-arg coroutine factories. The heartbeat ticks
(:mod:`bob.application.usecases.heartbeat`) are *one-shot* coroutines, so this
helper turns a tick into the periodic loop the runtime supervises: run the tick,
sleep, repeat.

Resilience is layered, inner to outer:

* a *transient* tick failure (a momentary network blip — ``Server disconnected``,
  a timeout, a 5xx) is retried with bounded exponential backoff via
  :func:`~bob.application.runtime.retry.retry_with_backoff`, configured by an
  optional :class:`RetryPolicy`;
* whatever the tick *ultimately* raises (a permanent error, or a transient one
  that never recovered) is logged and isolated, so one bad iteration can never
  kill the heartbeat and never stops the sibling ticks scheduled beside it;
* cancellation (on runtime stop) propagates cleanly.

Sleeping is injected so the loop and its backoff are deterministic in tests.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.runtime.retry import retry_with_backoff

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

logger = logging.getLogger(__name__)

# A one-shot tick: do a unit of work, then return.
type Tick = Callable[[], Awaitable[None]]

# An async sleep seam (defaults to asyncio.sleep), injectable for tests.
type Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded-backoff policy for retrying a tick's transient failures."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0


def periodic(
    tick: Tick,
    *,
    interval_seconds: float,
    sleep: Sleep | None = None,
    retry: RetryPolicy | None = None,
) -> Callable[[], Coroutine[object, object, None]]:
    """Return a runtime background factory that runs ``tick`` every interval.

    The returned coroutine factory loops forever: invoke ``tick`` (retrying
    transient failures with backoff when ``retry`` is given), isolate whatever it
    ultimately raises, then sleep ``interval_seconds``. It exits only on
    cancellation (which the runtime issues on stop).
    """
    _sleep: Sleep = sleep if sleep is not None else asyncio.sleep
    run_tick = _with_retry(tick, retry, _sleep) if retry is not None else tick

    async def loop() -> None:
        while True:
            try:
                await run_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("heartbeat tick failed; continuing")
            await _sleep(interval_seconds)

    return loop


def _with_retry(tick: Tick, retry: RetryPolicy, sleep: Sleep) -> Tick:
    """Wrap ``tick`` so transient failures retry with backoff before surfacing."""

    async def retried() -> None:
        await retry_with_backoff(
            tick,
            max_attempts=retry.max_attempts,
            base_delay_seconds=retry.base_delay_seconds,
            max_delay_seconds=retry.max_delay_seconds,
            sleep=sleep,
        )

    return retried
