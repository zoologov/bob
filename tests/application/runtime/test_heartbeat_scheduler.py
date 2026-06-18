# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``periodic`` — turning a tick into a supervised background loop."""

from __future__ import annotations

import asyncio

import pytest

from bob.application.runtime.heartbeat import periodic


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
