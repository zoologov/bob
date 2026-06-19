# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""retry_with_backoff — bounded exponential backoff over *transient* failures.

Bob's background ticks (:mod:`bob.application.usecases.heartbeat`) reach the LLM
endpoint, so an idle tick can catch a momentary network hiccup — a
``Server disconnected`` mid-request. Such a blip is *transient*: the right answer
is a short, bounded retry with exponential backoff, not a surfaced failure and
not an unbounded retry loop. A *permanent* error (a real bug, a 4xx) must be
surfaced immediately so backoff never masks a defect.

Two seams keep this deterministic and policy-driven:

* ``sleep`` is injected (defaults to :func:`asyncio.sleep`) so tests assert the
  backoff schedule with no real waiting.
* :func:`is_transient` classifies what is worth retrying — aiohttp connection
  failures (incl. ``Server disconnected``), timeouts, and 5xx responses — so the
  retry policy lives in one named place.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# An async sleep seam (defaults to asyncio.sleep), injectable for tests.
type Sleep = Callable[[float], Awaitable[None]]

# Default retry policy: a few quick attempts, then give up and surface.
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 0.5
_DEFAULT_MAX_DELAY_SECONDS = 30.0

# HTTP status at/above which a response error is a server-side (retryable) fault.
_SERVER_ERROR_STATUS = 500


def is_transient(error: BaseException) -> bool:
    """Whether ``error`` is a transient fault worth retrying.

    Transient = the operation may well succeed on a retry: network connection
    failures (aiohttp ``ClientConnectionError`` — which covers
    ``ServerDisconnectedError``), timeouts, and server-side 5xx responses.
    Everything else (4xx, structural/value errors, ordinary bugs) is permanent
    and surfaced immediately.
    """
    if isinstance(error, aiohttp.ClientResponseError):
        return error.status >= _SERVER_ERROR_STATUS
    return isinstance(
        error,
        aiohttp.ClientConnectionError | TimeoutError,
    )


async def retry_with_backoff[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = _DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = _DEFAULT_MAX_DELAY_SECONDS,
    sleep: Sleep | None = None,
) -> T:
    """Run ``operation``, retrying transient failures with exponential backoff.

    On a transient error (see :func:`is_transient`) the call is retried up to
    ``max_attempts`` times, sleeping ``base_delay_seconds * 2**n`` (capped at
    ``max_delay_seconds``) between attempts. A permanent error is re-raised at
    once. If every attempt fails transiently, the last error is surfaced so the
    caller (e.g. tick isolation) can log it — backoff stays bounded.
    """
    _sleep: Sleep = sleep if sleep is not None else asyncio.sleep
    last_attempt = max_attempts - 1
    for attempt in range(max_attempts):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not is_transient(error):
                raise
            if attempt == last_attempt:
                logger.warning(
                    "transient error persisted after %d attempt(s); surfacing: %r",
                    max_attempts,
                    error,
                )
                raise
            delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
            logger.info(
                "transient error on attempt %d/%d; retrying in %.3fs: %r",
                attempt + 1,
                max_attempts,
                delay,
                error,
            )
            await _sleep(delay)
    # Unreachable: the loop always returns or raises within max_attempts.
    msg = "retry_with_backoff exhausted its loop without returning"
    raise AssertionError(msg)
