# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for AgentRuntime (asyncio lifecycle: start / stop / graceful shutdown)."""

from __future__ import annotations

import asyncio

import pytest

from bob.application.runtime.agent import AgentRuntime, RuntimeState


@pytest.mark.asyncio
async def test_runtime_starts_in_stopped_state() -> None:
    # Arrange / Act
    runtime = AgentRuntime()

    # Assert
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.is_running is False


@pytest.mark.asyncio
async def test_start_transitions_to_running() -> None:
    # Arrange
    runtime = AgentRuntime()

    # Act
    await runtime.start()

    # Assert
    assert runtime.state is RuntimeState.RUNNING
    assert runtime.is_running is True

    # Cleanup
    await runtime.stop()


@pytest.mark.asyncio
async def test_stop_transitions_to_stopped() -> None:
    # Arrange
    runtime = AgentRuntime()
    await runtime.start()

    # Act
    await runtime.stop()

    # Assert
    assert runtime.state is RuntimeState.STOPPED
    assert runtime.is_running is False


@pytest.mark.asyncio
async def test_double_start_is_idempotent() -> None:
    # Arrange
    runtime = AgentRuntime()
    await runtime.start()

    # Act / Assert: starting an already-running runtime must not raise.
    await runtime.start()
    assert runtime.state is RuntimeState.RUNNING

    # Cleanup
    await runtime.stop()


@pytest.mark.asyncio
async def test_stop_when_already_stopped_is_noop() -> None:
    # Arrange
    runtime = AgentRuntime()

    # Act / Assert
    await runtime.stop()
    assert runtime.state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_registered_background_task_runs_while_running() -> None:
    # Arrange
    started = asyncio.Event()

    async def heartbeat() -> None:
        started.set()
        await asyncio.sleep(3600)  # would run forever; cancelled on stop

    runtime = AgentRuntime(background_tasks=[heartbeat])

    # Act
    await runtime.start()
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # Assert: the background task was scheduled and ran.
    assert started.is_set()

    # Cleanup
    await runtime.stop()


@pytest.mark.asyncio
async def test_stop_cancels_background_tasks_gracefully() -> None:
    # Arrange
    running = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker() -> None:
        running.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runtime = AgentRuntime(background_tasks=[worker])
    await runtime.start()
    await asyncio.wait_for(running.wait(), timeout=1.0)  # ensure task entered its body

    # Act
    await runtime.stop()

    # Assert: stop awaited graceful cancellation of the background task.
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_run_until_stopped_returns_after_stop() -> None:
    # Arrange
    runtime = AgentRuntime()
    await runtime.start()

    async def trigger_stop() -> None:
        await asyncio.sleep(0.01)
        await runtime.stop()

    # Act: run_until_stopped blocks until stop() is requested.
    await asyncio.gather(runtime.run_until_stopped(), trigger_stop())

    # Assert
    assert runtime.state is RuntimeState.STOPPED
