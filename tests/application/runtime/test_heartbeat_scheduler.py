# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``periodic`` — turning a tick into a supervised background loop."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from bob.application.runtime.heartbeat import RetryPolicy, periodic


@pytest.mark.asyncio
async def test_periodic_invokes_tick_repeatedly() -> None:
    # Arrange: a tick that records calls, and a sleep that yields instantly.
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    factory = periodic(tick, interval_seconds=0.0, sleep=fast_sleep)

    # Act: run the loop briefly, then cancel (as the runtime would on stop).
    task = asyncio.create_task(factory())
    while calls < 3:
        await asyncio.sleep(0)
    task.cancel()

    # Assert
    assert calls >= 3


@pytest.mark.asyncio
async def test_periodic_isolates_tick_errors() -> None:
    # Arrange: a tick that raises must not break the loop.
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    factory = periodic(flaky, interval_seconds=0.0, sleep=fast_sleep)

    # Act
    task = asyncio.create_task(factory())
    while calls < 2:
        await asyncio.sleep(0)
    task.cancel()

    # Assert: the loop survived the raised error and ticked again.
    assert calls >= 2


@pytest.mark.asyncio
async def test_periodic_retries_transient_tick_failure_then_succeeds() -> None:
    # Arrange: a tick that fails transiently once, then succeeds on retry.
    attempts = 0
    completed = 0

    async def flaky_once() -> None:
        nonlocal attempts, completed
        attempts += 1
        if attempts == 1:
            raise aiohttp.ServerDisconnectedError
        completed += 1

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    factory = periodic(
        flaky_once,
        interval_seconds=0.0,
        sleep=fast_sleep,
        retry=RetryPolicy(max_attempts=3, base_delay_seconds=0.0),
    )

    # Act
    task = asyncio.create_task(factory())
    while completed < 1:
        await asyncio.sleep(0)
    task.cancel()

    # Assert: the transient error was retried within the same iteration.
    assert attempts >= 2
    assert completed >= 1


@pytest.mark.asyncio
async def test_periodic_isolates_tick_that_exhausts_retries() -> None:
    # Arrange: a tick whose transient error never recovers must not kill the loop.
    iterations = 0

    async def always_transient() -> None:
        nonlocal iterations
        iterations += 1
        raise aiohttp.ServerDisconnectedError

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    factory = periodic(
        always_transient,
        interval_seconds=0.0,
        sleep=fast_sleep,
        retry=RetryPolicy(max_attempts=2, base_delay_seconds=0.0),
    )

    # Act
    task = asyncio.create_task(factory())
    while iterations < 4:
        await asyncio.sleep(0)
    task.cancel()

    # Assert: exhausted retries were isolated and the loop kept ticking.
    assert iterations >= 4


@pytest.mark.asyncio
async def test_one_failing_tick_does_not_stop_sibling_ticks() -> None:
    # Arrange: two independent periodic loops (as the runtime schedules them);
    # one always fails, the sibling must keep ticking unaffected.
    sibling_calls = 0

    async def broken() -> None:
        raise aiohttp.ServerDisconnectedError

    async def healthy() -> None:
        nonlocal sibling_calls
        sibling_calls += 1

    async def fast_sleep(_seconds: float) -> None:
        await asyncio.sleep(0)

    retry = RetryPolicy(max_attempts=2, base_delay_seconds=0.0)
    broken_loop = periodic(broken, interval_seconds=0.0, sleep=fast_sleep, retry=retry)
    healthy_loop = periodic(healthy, interval_seconds=0.0, sleep=fast_sleep)

    # Act: run both as separate supervised tasks.
    broken_task = asyncio.create_task(broken_loop())
    healthy_task = asyncio.create_task(healthy_loop())
    while sibling_calls < 3:
        await asyncio.sleep(0)
    broken_task.cancel()
    healthy_task.cancel()

    # Assert: the sibling progressed despite the broken loop next to it.
    assert sibling_calls >= 3
