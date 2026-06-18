# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the composition root (bob.app)."""

from __future__ import annotations

from datetime import datetime

import pytest

from bob.app import build_application
from bob.application.runtime import AgentRuntime, AsyncEventBus, RuntimeState
from bob.domain import ports


def test_build_application_returns_wired_runtime_and_bus() -> None:
    # Act
    app = build_application()

    # Assert: composition root produced the GUPPI runtime + event bus.
    assert isinstance(app.runtime, AgentRuntime)
    assert isinstance(app.event_bus, AsyncEventBus)
    assert app.runtime.state is RuntimeState.STOPPED


def test_build_application_wires_stub_ports() -> None:
    # Act
    app = build_application()

    # Assert: ports are filled with stubs satisfying their protocols.
    assert isinstance(app.clock, ports.Clock)
    assert isinstance(app.event_bus, ports.EventBus)
    assert isinstance(app.llm_provider, ports.LLMProvider)
    assert isinstance(app.memory_repo, ports.MemoryRepo)
    assert isinstance(app.memory_recall, ports.MemoryRecall)


def test_stub_clock_returns_timezone_aware_now() -> None:
    # Act
    app = build_application()
    now = app.clock.now()

    # Assert
    assert isinstance(now, datetime)
    assert now.tzinfo is not None


@pytest.mark.asyncio
async def test_application_runtime_starts_and_stops() -> None:
    # Arrange
    app = build_application()

    # Act
    await app.runtime.start()
    running = app.runtime.is_running
    await app.runtime.stop()

    # Assert
    assert running is True
    assert app.runtime.state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_stub_llm_provider_complete_is_awaitable() -> None:
    # Arrange
    app = build_application()

    # Act: the stub provider answers (walking-skeleton placeholder).
    result = await app.llm_provider.complete([{"role": "user", "content": "hi"}])

    # Assert
    assert isinstance(result, str)
