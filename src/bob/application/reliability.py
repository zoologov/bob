# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""call_with_retry — bounded async retry with an injected backoff sleep (BOB-049 .3).

The reliability primitive behind «full Bob or an honest GUPPI notice»: an ESSENTIAL
LLM step (the semantic judgment, the reply generation) is attempted a bounded number of
times, sleeping a short backoff between tries through an INJECTED sleep seam — so tests
stay deterministic (no real delay). If every attempt raises, the LAST exception is
re-raised, so the caller can fall back to the honest outage notice rather than ship a
degraded half-answer. A successful attempt returns immediately, without sleeping.

It is intentionally generic and policy-free: WHICH steps are essential, how many
attempts, and what to do on persistent failure all live in the caller.

Distinct from :func:`bob.application.runtime.retry.retry_with_backoff` by DESIGN: that
helper retries only *transient* faults (network blips / 5xx / timeouts) and surfaces a
permanent error at once, because a background tick must never mask a real bug. Here the
policy is the opposite on purpose — for a USER-FACING turn, ANY essential-step failure
(a timeout, a connection drop, OR an unparseable model answer) is worth a bounded retry
and then the honest GUPPI outage notice, since the only alternative is shipping a
degraded half-answer («уверенный бред»). Two different reliability policies, two helpers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["Sleep", "call_with_retry"]

logger = logging.getLogger(__name__)

# The injectable backoff seam: an awaitable sleep of N seconds. The runtime passes
# ``asyncio.sleep``; tests pass a fake that records the delay and returns at once.
type Sleep = Callable[[float], Awaitable[None]]


async def call_with_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    backoff_seconds: float,
    sleep: Sleep,
) -> T:
    """Call ``operation`` up to ``attempts`` times; re-raise the last error if all fail.

    Returns the first successful result. Between two attempts (never after the last) it
    awaits ``sleep(backoff_seconds)`` so the retry is paced without a hard delay in tests.
    ``attempts`` is the TOTAL number of tries (an initial call plus the retries); it must
    be at least 1.
    """
    if attempts < 1:
        msg = f"attempts must be >= 1, got {attempts}"
        raise ValueError(msg)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "retryable operation failed on attempt %d/%d: %s",
                attempt + 1,
                attempts,
                exc,
            )
            if attempt + 1 < attempts:
                await sleep(backoff_seconds)
    # The loop runs at least once and exits only via ``return`` or here with a stored
    # error, so ``last_exc`` is always set on this path.
    assert last_exc is not None
    raise last_exc
