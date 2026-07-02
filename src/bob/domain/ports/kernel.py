# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Kernel ports — infra-neutral runtime seams the whole domain rests on.

Time, the event bus, plain LLM completion, and the shared value objects
(:data:`LLMMessage`, :data:`JsonValue`) carried across every other port bucket.
These are *interfaces only*: structural :class:`typing.Protocol` definitions with
no implementations. Kernel is deliberately dependency-free of the other buckets —
``capabilities`` and ``social`` import *from here* (never the reverse). It lives in
``domain`` for now (infra-neutral, legal in the hexagon); Phase 3 relocates it to a
``runtime/`` package.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import (
    datetime,  # noqa: TC003 — runtime-resolvable for get_type_hints on the Clock port
)
from typing import Protocol, runtime_checkable

# A chat-style message for the LLM provider (OpenAI-compatible: role + content).
type LLMMessage = Mapping[str, str]

# A JSON-decodable soul-artifact value (object/array/scalar) carried by SoulStore.
type JsonValue = dict[str, object] | list[object] | str | int | float | bool | None


class DomainEvent(Protocol):
    """Marker contract for anything published on the :class:`EventBus`.

    Concrete events (``MessageReceived`` …) are defined in later beads; the bus
    only needs to know an event has a stable ``name`` for routing.
    """

    @property
    def name(self) -> str:
        """Stable event type name used for subscription routing."""
        ...


# A subscriber: an async callback invoked with the published event.
type EventHandler = Callable[[DomainEvent], Awaitable[None]]


@runtime_checkable
class Clock(Protocol):
    """Time source — injected so the domain never calls ``datetime.now()``.

    Enables deterministic tests and a single seam for time control.
    """

    def now(self) -> datetime:
        """Return the current timezone-aware time."""
        ...


@runtime_checkable
class EventBus(Protocol):
    """Asyncio publish/subscribe bus decoupling producers from consumers."""

    async def publish(self, event: DomainEvent) -> None:
        """Deliver ``event`` to every handler subscribed to its name."""
        ...

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register ``handler`` to receive events published under ``event_name``."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """OpenAI-compatible completion provider (Tier 0 local / Tier 1 API)."""

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat turn; yield tokens when ``stream`` is true."""
        ...
