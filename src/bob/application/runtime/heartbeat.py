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

:func:`health_gated` is the other lane wrapper (BOB-116): it sits between a tick and
:func:`periodic` and skips or probes the tick while the LLM provider the lane depends on
is declared degraded, so a dead provider costs one INFO line per probe instead of a
stack per tick. Both wrappers answer one question — how a one-shot tick runs as a lane.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.runtime.retry import retry_with_backoff

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from bob.kernel.ports import HealthReader

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


def health_gated(
    tick: Tick,
    *,
    reader: HealthReader,
    provider_id: str,
    probe: bool = False,
) -> Tick:
    """Gate a heartbeat lane on the health of the LLM provider it depends on (BOB-116).

    While ``provider_id`` is healthy the returned tick is ``tick`` in all but name: it
    runs and whatever it raises goes out unchanged. While the provider is declared
    degraded:

    * a lane with ``probe=False`` skips the tick — no call and no log line, because the
      monitor has already told the owner and a per-tick stack would only bury the logs;
    * a lane with ``probe=True`` runs the tick only when ``reader`` says a probe is due —
      the tick *is* the probe, and its success reaches the monitor through the router's
      ordinary report, which lifts the degradation and restores the ordinary rhythm. A
      failed probe is one INFO line without a stack; a probe not yet due is skipped
      silently.

    How a failed probe is told from another failure: by the provider's state, not by
    the exception's form. The router reports every failed call to the monitor *before*
    the exception reaches this lane, so a failure the provider caused shows up as a grown
    ``consecutive_failures`` in the reader's view of ``provider_id`` across the tick.
    Anything else — a database error before the call, or one after a probe the model
    answered (the monitor already reset the run) — leaves the count where it was and is
    re-raised, so :func:`periodic` logs it with its stack exactly as before.

    Limits, named honestly: the classification relies on the monitor being told
    synchronously within the failing call; a failure of the SAME provider recorded
    concurrently by another caller (a reply to a person failing during the probe) makes
    a non-LLM failure of this tick look like a failed probe and log as one INFO line; and
    a tick that swallows its own LLM error and then fails elsewhere is logged the same
    way. The gate guards only the provider it names: a lane that uses Tier-1 in part
    (the reflect reappraisal) is gated by ``tier1`` only as a whole, the rest of its
    steps go through the router's own door.
    """

    async def gated() -> None:
        if not reader.is_degraded(provider_id):
            await tick()
            return
        if not probe or not reader.probe_due(provider_id):
            return
        failures_before = _consecutive_failures(reader, provider_id)
        try:
            await tick()
        except Exception as exc:
            if _consecutive_failures(reader, provider_id) <= failures_before:
                raise
            _log_failed_probe(reader, provider_id, exc)

    return gated


def _consecutive_failures(reader: HealthReader, provider_id: str) -> int:
    """How many failures in a row the monitor has recorded for ``provider_id``."""
    view = reader.snapshot().get(provider_id)
    return 0 if view is None else view.consecutive_failures


def _log_failed_probe(reader: HealthReader, provider_id: str, exc: Exception) -> None:
    """One INFO line for a probe the provider failed — the monitor already recorded it."""
    view = reader.snapshot().get(provider_id)
    failure_class = None if view is None else view.failure_class
    logger.info(
        "heartbeat probe of %s failed (%s, %s); provider still degraded",
        provider_id,
        failure_class,
        type(exc).__name__,
    )
