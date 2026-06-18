# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Port protocols — the contracts the domain depends on (hexagonal boundary).

These are *interfaces only*: structural :class:`typing.Protocol` definitions with
no implementations. Adapters in ``bob.infrastructure`` realise them; ``bob.app``
wires concrete adapters to these ports. The domain never imports outward, so it
talks to transport / LLM / storage / time exclusively through these protocols.

Implementations (``OpenAICompatProvider``, ``SqliteMemoryRepo``, …) arrive in
later beads (.2-.4); BEAD-01 ships the contracts and stub/fake wiring only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from datetime import (
    datetime,  # noqa: TC003 — runtime-resolvable for get_type_hints on the Clock port
)
from typing import Protocol, runtime_checkable

__all__ = [
    "Clock",
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "JsonValue",
    "LLMMessage",
    "LLMProvider",
    "MemoryRecall",
    "MemoryRepo",
    "Recalled",
    "SoulStore",
]


# --- Shared value objects (plain data carried across ports) -------------------

# A chat-style message for the LLM provider (OpenAI-compatible: role + content).
type LLMMessage = Mapping[str, str]

# A single recalled memory item (content + relevance score), returned by recall.
type Recalled = Mapping[str, object]

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


# --- Ports --------------------------------------------------------------------


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


@runtime_checkable
class MemoryRepo(Protocol):
    """Persistent store for episodes, facts, and personality state (SQLite)."""

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        """Append one episodic event to durable storage."""
        ...

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent episodes (newest first)."""
        ...


@runtime_checkable
class MemoryRecall(Protocol):
    """Relevance retrieval over memory (P0: FTS5 keyword; seam for vectors)."""

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:
        """Return the top-``k`` memories relevant to ``query``."""
        ...


@runtime_checkable
class SoulStore(Protocol):
    """Reader/writer for Bob's on-disk soul artifacts (SOUL.md + JSON profiles).

    Genesis writes these once on first awakening; the runtime reads them on every
    boot. The concrete file-backed adapter lives in ``bob.infrastructure``.
    """

    def soul_exists(self) -> bool:
        """Whether ``SOUL.md`` has been written (Genesis-done signal on disk)."""
        ...

    def read_soul(self) -> str:
        """Return the SOUL.md narrative (raises if absent)."""
        ...

    def write_soul(self, markdown: str) -> None:
        """Write the SOUL.md narrative."""
        ...

    def write_json(self, name: str, data: JsonValue) -> None:
        """Write a JSON artifact ``<name>.json`` (e.g. ``taste_profile``)."""
        ...

    def append_genesis_log(self, line: str) -> None:
        """Append a line to the append-only genesis log."""
        ...
