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
from dataclasses import dataclass, field
from datetime import (
    datetime,  # noqa: TC003 — runtime-resolvable for get_type_hints on the Clock port
)
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.memory.entities import SemanticFact

__all__ = [
    "Capability",
    "Clock",
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "JsonValue",
    "LLMMessage",
    "LLMProvider",
    "MemoryRecall",
    "MemoryRepo",
    "Permission",
    "Recalled",
    "SoulStore",
    "ToolCall",
    "ToolCallResult",
    "ToolCallingProvider",
    "ToolDefinition",
]


# --- Shared value objects (plain data carried across ports) -------------------

# A chat-style message for the LLM provider (OpenAI-compatible: role + content).
type LLMMessage = Mapping[str, str]

# A single recalled memory item (content + relevance score), returned by recall.
type Recalled = Mapping[str, object]

# A JSON-decodable soul-artifact value (object/array/scalar) carried by SoulStore.
type JsonValue = dict[str, object] | list[object] | str | int | float | bool | None

# An OpenAI-shaped tool definition (``{"type": "function", "function": {...}}``),
# as emitted by the CapabilityRegistry manifest and sent to the LLM as ``tools``.
type ToolDefinition = Mapping[str, object]

# A capability's permission seam: "safe" runs straight through; "confirm" marks a
# capability that a future approval gate must clear before GUPPI executes it.
type Permission = Literal["safe", "confirm"]


# --- Capability seam (stable, forward-compatible) -----------------------------


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation the model asked for (OpenAI ``tool_calls`` shape).

    ``id`` correlates the call with the ``tool`` result message fed back into the
    next turn; ``name`` selects the capability; ``arguments`` are the decoded
    JSON arguments the capability's ``execute`` receives.
    """

    id: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallResult:
    """A tool-aware completion: free-text ``text`` plus any requested tool calls.

    When ``tool_calls`` is empty the turn is final and ``text`` is the answer;
    otherwise GUPPI must dispatch each call and feed the results back to loop.
    """

    text: str
    tool_calls: tuple[ToolCall, ...] = ()


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
class Capability(Protocol):
    """A single thing GUPPI can do for Bob — the stable capability seam.

    This is the contract, NOT the plugin machinery: a capability names itself,
    describes itself, advertises a JSON-Schema for its arguments, declares a
    ``permission`` (``"safe"`` runs straight through; ``"confirm"`` is the seam a
    future approval gate will read), and ``execute``s against decoded arguments.
    New skills register an object against this contract; consumers never change.
    """

    @property
    def name(self) -> str:
        """Unique tool name advertised to the model (OpenAI function name)."""
        ...

    @property
    def description(self) -> str:
        """Human/model-facing description of what the capability does."""
        ...

    @property
    def input_schema(self) -> Mapping[str, object]:
        """JSON-Schema object describing the capability's arguments."""
        ...

    @property
    def permission(self) -> Permission:
        """Approval seam: ``"safe"`` or ``"confirm"`` (future gate)."""
        ...

    async def execute(self, args: Mapping[str, object]) -> object:
        """Run the capability against ``args`` and return its result."""
        ...


@runtime_checkable
class ToolCallingProvider(Protocol):
    """An LLM provider that can be handed ``tools`` and return ``tool_calls``.

    The tool-aware sibling of :class:`LLMProvider`: given the conversation and a
    manifest of tool definitions, it returns a :class:`ToolCallResult` (final
    text, or the tool calls the model requested). Adapters realise this over a
    native OpenAI ``tools`` round-trip or a prompt-protocol fallback.
    """

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        """Complete a turn that may request tool calls."""
        ...


@runtime_checkable
class MemoryRepo(Protocol):
    """Persistent store for episodes, facts, and personality state (SQLite)."""

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        """Append one episodic event to durable storage."""
        ...

    async def save_fact(self, fact: SemanticFact) -> None:
        """Persist one durable semantic fact (the FTS index is updated too)."""
        ...

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent episodes (newest first)."""
        ...

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        """Return the last ``k`` episodes by recency, in chronological order.

        Oldest-first within the window so callers can replay recent conversation
        history into a reply prompt; a non-positive ``k`` yields an empty sequence.
        """
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
