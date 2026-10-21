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
:class:`ToolCallResult`, :class:`ToolCallingProvider` — beside :data:`ToolLoopMessage`);
and the LLM provider-health seams both ``application`` and ``infrastructure`` speak
(BOB-116): :class:`HealthObserver`, :class:`HealthReader`, :class:`OwnerAlertSink` and the
:class:`HealthView` snapshot.
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

from bob.kernel.provider_health import (
    HealthState,  # noqa: TC001 — runtime-resolvable for get_type_hints on HealthView
)

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


# --- LLM provider health (BOB-116: read by application AND infrastructure) ------------


@dataclass(frozen=True)
class HealthView:
    """Read-only snapshot of one provider's health, for ``/status`` and the lane gates.

    ``failing_since`` is the timezone-aware start of the current failure run (``None``
    while nothing has failed); ``failure_class`` is the latest failure class the caller
    reported (``auth`` / ``rate`` / ``server`` / ``timeout`` / ``connection`` /
    ``shape`` / ``contract``).

    ``stood_down_reason`` — why the provider was taken out of service at startup (BOB-116
    D11: the understudy enabled in the config but not ready); such a provider gets no calls
    until the process restarts. ``None`` for every provider in service.
    """

    state: HealthState
    consecutive_failures: int = 0
    failure_class: str | None = None
    failing_since: datetime | None = None
    stood_down_reason: str | None = None


@runtime_checkable
class HealthObserver(Protocol):
    """Where the router and the understudy wrapper report the outcome of every call.

    ``provider_id`` is ``tier0-primary`` / ``tier0-understudy`` / ``tier1``. The calls are
    async because a transition may message the owner; an implementation swallows its own
    delivery errors — reporting an outcome never fails the call being reported.
    """

    async def record_success(self, provider_id: str) -> None:
        """The provider answered."""
        ...

    async def record_failure(self, provider_id: str, failure_class: str) -> None:
        """The provider failed with ``failure_class``."""
        ...


@runtime_checkable
class SelfReportingProvider(Protocol):
    """A provider that reports the outcome of each of its own calls (BOB-116 F1).

    The optional companion of :class:`LLMProvider` the health-reporting wrapper advertises.
    The factory puts the wrapper on a tier so that EVERY caller's call is reported — the
    router's and the tool loop's alike, which calls Tier 1 past the router. A caller that
    also reports (the router) asks this protocol whether the call is already accounted for:
    reporting it again would count one HTTP call twice.
    """

    @property
    def reported_id(self) -> str:
        """The ``provider_id`` this provider's outcomes are reported under."""
        ...


@runtime_checkable
class HealthReader(Protocol):
    """Read side of provider health: the ``/status`` snapshot, the heartbeat lane gate and
    the understudy wrapper's breaker.

    The ids a reader answers for are the ones in :mod:`bob.kernel.provider_health`: the
    providers outcomes are reported under (``tier0-primary``, ``tier0-understudy``,
    ``tier1``) and one id that is not a provider — ``TIER0_EFFECTIVE`` (``"tier0"``), Tier 0
    as a whole. A reader that does not know an id reads it as healthy, so a reader wired
    into the lane gate MUST answer ``TIER0_EFFECTIVE`` or the gate never closes.
    """

    def snapshot(self) -> Mapping[str, HealthView]:
        """Every known provider's health, keyed by ``provider_id``; no ``TIER0_EFFECTIVE``."""
        ...

    def is_degraded(self, provider_id: str) -> bool:
        """Whether ``provider_id`` is currently declared out of service.

        For a provider id — its own state (a provider stood down at startup is degraded).
        For ``TIER0_EFFECTIVE`` — whether Tier 0 has nothing to think with: the cloud is
        degraded AND the understudy is absent, stood down or degraded too. An unknown id is
        healthy.
        """
        ...

    def probe_due(self, provider_id: str) -> bool:
        """Whether a call to ``provider_id`` may go now.

        A healthy provider — always; a degraded one — when its probe schedule says so; one
        stood down at startup — never. Asked for provider ids, not for ``TIER0_EFFECTIVE``.
        """
        ...


@runtime_checkable
class OwnerAlertSink(Protocol):
    """A direct message to the owner that does not go through the LLM.

    Distinct from the restart announcement (different meaning, BOB-116 CONTEXT): this path
    must work precisely when the model stack is what broke.
    """

    async def notify_owner(self, text: str) -> None:
        """Deliver ``text`` to the owner's private chat."""
        ...
