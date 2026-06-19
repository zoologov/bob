# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``retry_with_backoff`` — bounded exponential backoff on transients.

A heartbeat tick can catch a *transient* network hiccup (a momentary
``Server disconnected`` from the LLM endpoint). Such a blip should be retried a
bounded number of times with exponential backoff, not surfaced as a failure and
not retried forever. A *permanent* error (a bug, a 4xx) must be surfaced
immediately so backoff never masks a real defect. Sleeping is injected so the
backoff schedule is asserted deterministically with no real waiting.
"""

from __future__ import annotations

import aiohttp
import pytest

from bob.application.runtime.retry import is_transient, retry_with_backoff


class _BoomError(RuntimeError):
    """A permanent, non-network error (stands in for a real bug)."""


def _response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=None,  # type: ignore[arg-type]  # not inspected by the classifier
        history=(),
        status=status,
    )


@pytest.mark.asyncio
async def test_transient_failure_is_retried_then_succeeds() -> None:
    # Arrange: fail twice with a transient error, then succeed.
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise aiohttp.ServerDisconnectedError
        return "ok"

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    # Act
    result = await retry_with_backoff(
        flaky,
        max_attempts=5,
        base_delay_seconds=0.5,
        sleep=record_sleep,
    )

    # Assert: succeeded on the third attempt, with exponential backoff between.
    assert result == "ok"
    assert attempts == 3
    assert slept == [0.5, 1.0]


@pytest.mark.asyncio
async def test_permanent_error_is_surfaced_without_retry() -> None:
    # Arrange: a permanent error must not be retried at all.
    attempts = 0

    async def buggy() -> None:
        nonlocal attempts
        attempts += 1
        raise _BoomError("real bug")

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    # Act / Assert: surfaced immediately, no backoff, called exactly once.
    with pytest.raises(_BoomError):
        await retry_with_backoff(
            buggy,
            max_attempts=5,
            base_delay_seconds=0.5,
            sleep=record_sleep,
        )
    assert attempts == 1
    assert slept == []


@pytest.mark.asyncio
async def test_transient_error_that_never_recovers_is_bounded() -> None:
    # Arrange: a transient error that always fires — retries are bounded.
    attempts = 0

    async def always_transient() -> None:
        nonlocal attempts
        attempts += 1
        raise aiohttp.ServerDisconnectedError

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    # Act / Assert: surfaces the last transient error after max_attempts tries.
    with pytest.raises(aiohttp.ServerDisconnectedError):
        await retry_with_backoff(
            always_transient,
            max_attempts=3,
            base_delay_seconds=0.5,
            sleep=record_sleep,
        )
    assert attempts == 3
    # Backoff between each of the failed attempts, but not after the last.
    assert slept == [0.5, 1.0]


@pytest.mark.asyncio
async def test_backoff_is_capped() -> None:
    # Arrange: many failures — the per-attempt delay must not exceed max_delay.
    attempts = 0

    async def always_transient() -> None:
        nonlocal attempts
        attempts += 1
        raise aiohttp.ServerDisconnectedError

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    # Act / Assert
    with pytest.raises(aiohttp.ServerDisconnectedError):
        await retry_with_backoff(
            always_transient,
            max_attempts=6,
            base_delay_seconds=1.0,
            max_delay_seconds=4.0,
            sleep=record_sleep,
        )
    # 1, 2, 4, then capped at 4, 4.
    assert slept == [1.0, 2.0, 4.0, 4.0, 4.0]


@pytest.mark.asyncio
async def test_succeeds_first_try_without_sleeping() -> None:
    async def happy() -> int:
        return 42

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    result = await retry_with_backoff(happy, sleep=record_sleep)

    assert result == 42
    assert slept == []


@pytest.mark.parametrize(
    "exc",
    [
        aiohttp.ServerDisconnectedError(),
        aiohttp.ClientConnectionError(),
        TimeoutError(),
        _response_error(500),
        _response_error(503),
    ],
)
def test_is_transient_recognises_network_and_5xx(exc: BaseException) -> None:
    assert is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        _BoomError(),
        ValueError("structural"),
        _response_error(400),
        _response_error(404),
    ],
)
def test_is_transient_rejects_permanent(exc: BaseException) -> None:
    assert is_transient(exc) is False
