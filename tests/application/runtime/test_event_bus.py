# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the asyncio EventBus (publish/subscribe)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.domain import ports


@dataclass(frozen=True)
class _Event:
    name: str
    payload: str = ""


def test_async_event_bus_satisfies_event_bus_port() -> None:
    # Assert the implementation structurally satisfies the domain port.
    assert isinstance(AsyncEventBus(), ports.EventBus)


@pytest.mark.asyncio
async def test_publish_invokes_subscribed_handler() -> None:
    # Arrange
    bus = AsyncEventBus()
    received: list[str] = []

    async def handler(event: ports.DomainEvent) -> None:
        received.append(event.name)

    bus.subscribe("ping", handler)

    # Act
    await bus.publish(_Event(name="ping"))

    # Assert
    assert received == ["ping"]


@pytest.mark.asyncio
async def test_publish_routes_only_to_matching_subscribers() -> None:
    # Arrange
    bus = AsyncEventBus()
    pings: list[str] = []
    pongs: list[str] = []

    async def on_ping(event: ports.DomainEvent) -> None:
        pings.append(event.name)

    async def on_pong(event: ports.DomainEvent) -> None:
        pongs.append(event.name)

    bus.subscribe("ping", on_ping)
    bus.subscribe("pong", on_pong)

    # Act
    await bus.publish(_Event(name="ping"))

    # Assert: only the matching handler fired.
    assert pings == ["ping"]
    assert pongs == []


@pytest.mark.asyncio
async def test_multiple_handlers_for_same_event_all_run() -> None:
    # Arrange
    bus = AsyncEventBus()
    calls: list[int] = []

    async def first(event: ports.DomainEvent) -> None:
        calls.append(1)

    async def second(event: ports.DomainEvent) -> None:
        calls.append(2)

    bus.subscribe("tick", first)
    bus.subscribe("tick", second)

    # Act
    await bus.publish(_Event(name="tick"))

    # Assert
    assert sorted(calls) == [1, 2]


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop() -> None:
    # Arrange
    bus = AsyncEventBus()

    # Act / Assert: publishing an unsubscribed event must not raise.
    await bus.publish(_Event(name="orphan"))


@pytest.mark.asyncio
async def test_one_failing_handler_does_not_block_others() -> None:
    # Arrange
    bus = AsyncEventBus()
    survivors: list[str] = []

    async def boom(event: ports.DomainEvent) -> None:
        raise RuntimeError("handler failure")

    async def ok(event: ports.DomainEvent) -> None:
        survivors.append(event.name)

    bus.subscribe("ping", boom)
    bus.subscribe("ping", ok)

    # Act: a failing handler is isolated; the bus keeps delivering.
    await bus.publish(_Event(name="ping"))

    # Assert
    assert survivors == ["ping"]
