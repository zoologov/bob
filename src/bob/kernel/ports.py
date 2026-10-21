# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Kernel ports — infra-neutral runtime seams the whole system rests on.

Time, the event bus, plain LLM completion, and the shared value objects
(:data:`LLMMessage`, :data:`JsonValue`) carried across every other port bucket;
plus the cross-module seams several contexts BELOW their old owner read (BOB-113):
the memory read ports (:class:`EpisodeReader`, :class:`MemoryRecall`), the outgoing
reply channel (:class:`ReplyGateway`), Bob's own id (:class:`BobUserIdSource`) and the
LLM tool-calling vocabulary (:data:`ToolDefinition`, :class:`ToolCall`,
:class:`ToolCallResult`, :class:`ToolCallingProvider` — beside :data:`ToolLoopMessage`).
These are *interfaces only*: structural :class:`typing.Protocol` definitions with
no implementations. The kernel is deliberately dependency-free of the modules —
every module (``capabilities`` / ``social`` / …) imports *from here*, never the
reverse. It lives in ``bob.kernel`` as a shared kernel: infra-neutral cross-module
contracts, legal for any module to import, with no cycles.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import (
    datetime,  # noqa: TC003 — runtime-resolvable for get_type_hints on the Clock port
)
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from bob.kernel.episode_types import Recalled

# A chat-style message for the LLM provider (OpenAI-compatible: role + content).
type LLMMessage = Mapping[str, str]

# A tool-loop chat message: like :data:`LLMMessage`, but a value may be a STRUCTURAL
# ``tool_calls`` array — the assistant's native tool-call turn (a list of
# ``{"id","type","function":{…}}`` objects) — so values are typed ``object`` not
# ``str`` (BOB-069). Only the tool-loop re-ask carries this richer shape; plain
# completion stays string-only, so the wider type does not leak into every message.
type ToolLoopMessage = Mapping[str, object]

# An OpenAI-shaped tool definition (``{"type": "function", "function": {...}}``),
# as emitted by the CapabilityRegistry manifest and sent to the LLM as ``tools``.
type ToolDefinition = Mapping[str, object]

# A JSON-decodable soul-artifact value (object/array/scalar) carried by SoulStore.
type JsonValue = dict[str, object] | list[object] | str | int | float | bool | None


class DomainEvent(Protocol):
    """Marker contract for anything published on the :class:`EventBus`.

    Concrete events (``MessageReceived`` …) live in :mod:`bob.kernel.events`; the bus
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


@runtime_checkable
class UnderstudyBackedProvider(Protocol):
    """A provider that may quietly answer on a STAND-IN model when its endpoint is out.

    The optional companion of :class:`LLMProvider` a *composite* provider advertises
    (BOB-087.E-M1). Such a composite is invisible to its caller by design — it returns an
    ordinary string — which is exactly right for a служебный ход and exactly wrong for a
    turn that ships to a human AS BOB: a weak stand-in would be published in his voice.
    Declaring the capability lets the caller ask two things it otherwise could not: whether
    a stand-in exists at all, and — via :meth:`without_understudy` — for the primary alone.
    """

    def without_understudy(self) -> LLMProvider:
        """The primary alone: same endpoint, but it FAILS instead of degrading."""
        ...


# --- Memory read seams (BOB-113: read below memory, so they live here) ----------


class EpisodeReader(Protocol):
    """The read seam HandleMessage needs: replay recent conversation history."""

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]: ...

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        """Replay the last ``k`` turns WITH one sender (per-person thread, BOB-045)."""
        ...


@runtime_checkable
class MemoryRecall(Protocol):
    """Relevance retrieval over memory (P0: FTS5 keyword; seam for vectors)."""

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        """Return the top-``k`` memories relevant to ``query``.

        ``surface_old`` is an ADDITIVE opt-in (BOB-021 mechanism 1): when set, an
        implementation MAY blend ONE old-but-relevant memory into the result (relevant
        by embedding, biased toward an older timestamp) so a deep cut can surface that
        recency ordering would otherwise drop. It defaults off — the default call is a
        drop-in, unchanged contract — and an implementation with no age signal
        (keyword-only) treats it as a graceful no-op.
        """
        ...


# --- Outgoing reply channel + Bob's own id (BOB-113) ---------------------------


class ReplyGateway(Protocol):
    """The Telegram seam HandleMessage needs (BOB-009).

    ``typing_indicator`` wraps the slow generation so "Bob is typing…" stays
    visible for the whole wait; ``reply`` commits the finished answer once (rich,
    plain fallback). No token streaming — Bob can't stream in a group topic.
    """

    def typing_indicator(
        self, *, chat_id: int
    ) -> AbstractAsyncContextManager[None]: ...

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> int | None: ...

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None: ...

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None: ...


class BobUserIdSource(Protocol):
    """Read seam: Bob's own bot ``user_id``, resolved at startup (BOB-023).

    The addressivity detector needs Bob's numeric Telegram id to tell a reply that
    targets *Bob* from a reply that targets someone else. The id is resolved
    asynchronously at startup (``get_me`` → ``BotIdentitySignals.user_id``) — long
    after this synchronous use-case is constructed — so it is read lazily through
    this seam, which yields ``None`` until identity is resolved (or for the GUPPI
    gateway, which has none). A ``None`` degrades gracefully: reply-to-Bob simply
    cannot fire, while @mention-of-Bob addressivity still works.
    """

    def __call__(self) -> int | None: ...


# --- LLM tool-calling vocabulary (BOB-113; ToolLoopMessage + ToolDefinition above) ---


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


@runtime_checkable
class ToolCallingProvider(Protocol):
    """An LLM provider that can be handed ``tools`` and return ``tool_calls``.

    The tool-aware sibling of :class:`~bob.kernel.ports.LLMProvider`: given the
    conversation and a manifest of tool definitions, it returns a
    :class:`ToolCallResult` (final text, or the tool calls the model requested).
    Adapters realise this over a native OpenAI ``tools`` round-trip or a prompt-protocol
    fallback.
    """

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        """Complete a turn that may request tool calls."""
        ...
