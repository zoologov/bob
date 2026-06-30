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
    from bob.domain.coding.entities import CodingSession
    from bob.domain.goals.entities import Goal, Task
    from bob.domain.goals.graph import GoalGraph
    from bob.domain.goals.state import GoalState, TaskState
    from bob.domain.memory.entities import SemanticFact
    from bob.domain.personality.conversation_floor import ConversationFloor
    from bob.domain.personality.fascination import Fascination
    from bob.domain.personality.first_impression import FirstImpression
    from bob.domain.personality.negotiation import NegotiationZone
    from bob.domain.personality.reaction_effect import NotableReaction
    from bob.domain.personality.relationship import Relationship
    from bob.domain.personality.self_improvement import (
        ImprovementRule,
        ImprovementSignals,
        RuleState,
    )
    from bob.domain.personality.sulk import SulkState
    from bob.domain.personality.taste import Verdict
    from bob.domain.proactivity.state import ProactivityState

__all__ = [
    "AllowlistStore",
    "Capability",
    "ClaudeCodeRunner",
    "Clock",
    "CodingSessionStore",
    "ConversationFloorStore",
    "DiagramRenderError",
    "DiagramRenderer",
    "DiagramResult",
    "DiagramSink",
    "DomainEvent",
    "Embedder",
    "EventBus",
    "EventHandler",
    "FascinationStore",
    "FirstImpressionStore",
    "GoalStore",
    "JsonValue",
    "LLMMessage",
    "LLMProvider",
    "MemoryRecall",
    "MemoryRepo",
    "MessageReactor",
    "NotableReactionStore",
    "PatternDetector",
    "Permission",
    "Planner",
    "ProactivityStore",
    "PullRequestOpener",
    "Recalled",
    "ReflectionReader",
    "RelationshipStore",
    "RepoIntrospector",
    "Reranker",
    "SelfImprovementStore",
    "SoulStore",
    "SulkStore",
    "ToolCall",
    "ToolCallResult",
    "ToolCallingProvider",
    "ToolDefinition",
    "WebSearchProvider",
    "WebSearchResult",
    "WebSource",
    "Worktree",
    "ZoneClassifier",
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


@dataclass(frozen=True, slots=True)
class WebSource:
    """One grounding source a web search returned: a human ``title`` and its ``url``.

    Provider-agnostic (BOB-053): the Qwen-native Responses API yields a ``url`` and
    sometimes a ``title``; ``title`` is ``""`` when the provider omits it (a URL alone
    is enough for v1). Immutable so a recalled source cannot be tampered with downstream.
    """

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    """A grounded web-search answer plus its sources (the ``web_search`` skill payload).

    ``answer`` is the provider's grounded reply; ``sources`` is the (possibly empty)
    list of :class:`WebSource` it cited. Empty ``sources`` is valid — a grounded answer
    with nothing worth citing — NOT an error. The skill (.2) projects this compactly
    into the tool-loop; Bob synthesises the final reply in his own voice with links.
    """

    answer: str
    sources: tuple[WebSource, ...] = ()


class DiagramRenderError(Exception):
    """Raised by a :class:`DiagramRenderer` when it cannot render (BOB-035).

    The port's failure contract — defined in the domain so the application
    (``render_diagram``) can catch it WITHOUT importing infrastructure (the hexagon
    forbids application → infrastructure). An adapter
    (:class:`~bob.infrastructure.diagrams.mmdc_renderer.SubprocessMmdcRenderer`)
    raises it when the local mermaid-cli is absent, exits non-zero, times out, or
    produces no PNG, so the capability degrades to an honest "renderer unavailable"
    line and never crashes the turn. The infra module re-exports it for adapters.
    """


@dataclass(frozen=True)
class DiagramResult:
    """A rendered diagram a capability produced: the PNG bytes plus a short caption.

    The structured result the ``render_diagram`` capability returns instead of plain
    text. ``png`` is the rendered image (the local mermaid-cli output), and
    ``caption`` is a short human/model-facing line ("вот диаграмма") sent alongside
    the image. ``source`` is the mermaid the diagram was rendered FROM — the dedup key
    (BOB-037) so an inline ```mermaid block in Bob's reply is not re-rendered when the
    ``render_diagram`` tool already rendered the same source this turn; it defaults to
    ``""`` for callers that do not track it. The capability hands this to the per-turn
    :class:`DiagramSink` so the reply path — which holds the per-turn ``chat_id`` and
    the gateway — can send the image into the chat; the tool-loop only ever sees the
    caption text. It carries NO chat_id (the send is a transport concern resolved per
    turn), keeping the domain pure of transport.
    """

    png: bytes
    caption: str
    source: str = ""


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
class WebSearchProvider(Protocol):
    """Search the web and return a grounded answer with sources (BOB-053).

    The provider-agnostic seam the ``web_search`` skill delegates to: given a
    ``query``, return a :class:`WebSearchResult` (a grounded ``answer`` plus the
    ``sources`` it cited). The first realisation is Qwen-native over the MaaS
    Responses API (``QwenWebSearchProvider``), but the port commits only to "query in,
    grounded answer + sources out" so Tavily or another provider swaps in without any
    skill change. An implementation RAISES on any failure (network, non-200, or a
    malformed/absent expected field) — the caller (.3) owns fault-tolerance and Bob
    never confabulates a "found" answer. An empty ``sources`` list is allowed (a
    grounded answer with nothing worth citing), not a failure.
    """

    async def search(self, query: str) -> WebSearchResult:
        """Return a grounded answer with sources for ``query`` (raises on failure)."""
        ...


@runtime_checkable
class Planner(Protocol):
    """Decompose a goal into executable tasks (the Planner seam, BOB-015 .2).

    Given an APPROVED :class:`~bob.domain.goals.entities.Goal`, an implementation
    asks an LLM (Tier-1 reasoning) to break it into atomic
    :class:`~bob.domain.goals.entities.Task` units — each carrying its ``deps``
    (predecessor task ids, same goal) and the ``needs_external_agency`` flag
    classifying whether it requires stage-C (code / external tools / filesystem /
    external APIs). Returned tasks are fresh, in :class:`TaskState.NEW`. The
    contract is deliberately abstract: the live realisation parses strict JSON from
    a reasoning model (markdown-fenced / preamble-tolerant, like fact extraction),
    and a deterministic fake decomposes in tests with no network.
    """

    async def decompose(self, goal: Goal) -> Sequence[Task]:
        """Return the tasks ``goal`` decomposes into (in :class:`TaskState.NEW`)."""
        ...


@runtime_checkable
class PatternDetector(Protocol):
    """Formulate candidate rules from signals about Bob's own behaviour (BOB-028 .2).

    The metacognitive detector: given :class:`ImprovementSignals` (a slice of Bob's
    self-observations — self-repeats, addressivity outcomes, verbosity misses,
    relationship deltas, a stuck mood, owner friction, what landed) it returns
    candidate :class:`~bob.domain.personality.self_improvement.ImprovementRule`
    objects — EACH strictly in ``state=PROPOSED`` and ``origin=BOB_PROPOSED`` (the
    detector only PROPOSES; only the owner approval of the .3 use-case moves a rule to
    APPROVED), with ``lever`` taken ONLY from the hard
    :class:`~bob.domain.personality.self_improvement.Lever` allowlist and ``magnitude``
    in ``[0, 1]`` (application .3 clamps it again).

    The contract is abstract on purpose: the live realisation asks an LLM and parses
    strict JSON as tolerantly as fact extraction (markdown-fenced / preamble / trailing
    garbage tolerated; malformed output -> an empty sequence, never a raise), while a
    deterministic fake proposes in tests with no network. No I/O in the contract.
    """

    async def detect(self, signals: ImprovementSignals) -> Sequence[ImprovementRule]:
        """Return candidate rules in ``PROPOSED`` (empty when there are no patterns)."""
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


@runtime_checkable
class MessageReactor(Protocol):
    """Set a native reaction on a received message (the react-only seam, BOB-018).

    On a :data:`~bob.domain.personality.expression.ExpressionMode.REACT_ONLY` turn
    Bob acknowledges with a single emoji reaction *instead of* composing a reply —
    cheap, no LLM. The Telegram realisation calls ``set_message_reaction``; the
    ``emoji`` is always one Bob picked from the standard reaction set
    (:func:`~bob.domain.personality.reaction.reaction_emoji_for`). The reaction is
    **best-effort**: an adapter MUST degrade gracefully (a textual ack, or a no-op)
    on any transport error and never raise into the caller, so a failed reaction
    can never break a turn.
    """

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        """React to ``message_id`` in ``chat_id`` with ``emoji`` (best-effort)."""
        ...


@runtime_checkable
class ReflectionReader(Protocol):
    """Read the text of Bob's most recent REAL reflection (the leak-inner-life seam).

    On a :data:`~bob.domain.personality.expression.ExpressionPlan.leak_inner_life`
    turn the compose path injects this text so Bob's reply carries a glimpse of what
    he caught himself thinking about — but only from a real, persisted reflection
    (an ``episodic_log`` row whose ``event_type`` is ``reflection`` or
    ``inner_monologue``, already grounded and in the persona language by BOB-012).
    There is NO fabrication: ``None`` means there is no real reflection on record, so
    the leak no-ops. The concrete adapter reads SQLite in ``bob.infrastructure``.
    """

    async def latest_reflection_text(self) -> str | None:
        """Return the most recent real reflection's text, or ``None`` if there is none."""
        ...


@runtime_checkable
class RepoIntrospector(Protocol):
    """Read-only self-introspection over Bob's own repo + tracker (BOB-017 Phase A).

    The seam Bob's introspection skills (``inspect_architecture`` / ``read_code`` /
    ``list_work``, arriving in .2) delegate to so they never touch I/O directly.
    Every method is **read-only**: an implementation may shell out to local
    ``beadloom`` / ``bd`` (a FIXED allowlist of read subcommands, never a shell) or
    read a source file — but never writes, executes arbitrary commands, or reaches
    the network. The privacy invariant is enforced INSIDE the implementation, not by
    the caller: :meth:`read_file` consults the
    :class:`~bob.domain.introspection.privacy_guard.PrivacyGuard` before opening a
    file and sanitises output, so a denied path (SOUL / DB / ``.env`` / ``config``)
    can never be read. The contract is deliberately abstract — the live realisation
    is the subprocess adapter in ``bob.infrastructure.introspection``; a deterministic
    fake substitutes in tests with no subprocess and no disk.
    """

    async def architecture_context(self, ref: str) -> str:
        """Return grounded architecture context for ``ref`` (beadloom, read-only).

        ``ref`` may be an exact graph ref-id OR a free-text question: the
        implementation routes free text through search and an exact ref through the
        graph (falling back to search when the ref does not resolve) so a natural
        question always grounds rather than returning empty.
        """
        ...

    async def search_code(self, query: str) -> str:
        """Return a compact result of searching the repo/graph for ``query``."""
        ...

    async def read_file(self, path: str, *, max_lines: int) -> str:
        """Return up to ``max_lines`` of ``path`` — guard-checked BEFORE opening.

        Raises / returns a refusal (implementation-defined, never a disk read) when
        the privacy guard denies ``path``; otherwise the text is sanitised before
        return.
        """
        ...

    async def list_tasks(self, query: str) -> str:
        """Return tracker state for ``query`` (``bd`` ready/show/list, read-only).

        Routes a task id to ``bd show``, a closed/recent/in-progress/all listing
        request to the matching ``bd list``, and an empty/"ready" query to the ready
        queue. Tooling-noise tail lines are stripped before return.
        """
        ...

    async def code_history(self, path: str) -> str:
        """Return the read-only git history linking ``path`` to its decisions (BOB-038).

        ``path`` is either a repo-relative source path — yielding the bounded
        ``git log --oneline`` of that file/dir — or a bead key (``BOB-031`` /
        ``bob-4be.1``), yielding the commits whose message mentions that key
        (``git log --grep=<key> --oneline``). The implementation runs git only as a
        FIXED set of read-only ``log`` invocation forms with the path/key validated;
        a path-injection, an arbitrary flag, or any non-``log`` subcommand is refused
        (never executed). Output is sanitised and truncated like the other reads.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    """Maps texts to dense embedding vectors (the semantic-memory seam).

    Provider-agnostic by design: an Ollama-backed adapter (BGE-M3, 1024-dim) is
    the first realisation, but the port commits only to "text in, one vector per
    text out" so a later local model (e.g. Qwen3-Embedding) swaps in without any
    consumer change. Embeddings stay local for privacy — memory content never
    leaves the machine. The vector dimension is fixed by the configured model.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` into one dense vector each (order-preserving).

        Returns a list aligned with ``texts``: element ``i`` is the embedding of
        ``texts[i]``. Every vector shares the model's fixed dimension. An empty
        input yields an empty list.
        """
        ...


@runtime_checkable
class DiagramRenderer(Protocol):
    """Render mermaid source to a PNG image — the LOCAL diagram-render seam (BOB-035).

    The pure abstraction the ``render_diagram`` capability delegates to: given the
    mermaid source the user (or Bob) wrote, return the rendered PNG bytes. The
    realisation runs strictly LOCALLY (privacy — diagram source never leaves the
    machine): the first adapter
    (:class:`~bob.infrastructure.diagrams.mmdc_renderer.SubprocessMmdcRenderer`)
    shells the local mermaid-cli (``mmdc``) via ``create_subprocess_exec`` (never a
    shell), but the port commits only to "mermaid in, PNG bytes out" so a pure-Python
    renderer could swap in without any consumer change. An implementation MUST raise a
    clear :class:`DiagramRenderError` when
    it cannot render (the binary is absent, the source is malformed, a timeout) so the
    capability degrades to an honest "renderer unavailable" line and never crashes the
    turn. The contract is abstract on purpose; a deterministic fake substitutes in
    tests with no subprocess.
    """

    async def render(self, mermaid_source: str) -> bytes:
        """Render ``mermaid_source`` to PNG bytes (raises when it cannot render)."""
        ...


@runtime_checkable
class DiagramSink(Protocol):
    """Per-turn collector for rendered diagrams awaiting a photo send (BOB-035).

    The seam that carries a :class:`DiagramResult` from the ``render_diagram``
    capability (dispatched deep inside the global registry's tool-loop, with no
    ``chat_id``) out to the reply path (which holds the per-turn ``chat_id`` and the
    gateway). The capability :meth:`push`es each rendered diagram; after the tool-loop
    the reply path :meth:`drain`s them and sends each as a Telegram photo, keeping the
    chat_id strictly per-turn and the send a transport concern. ``drain`` returns the
    collected results and clears the sink, so each turn starts empty (no leak across
    turns).
    """

    def push(self, result: DiagramResult) -> None:
        """Record one rendered diagram for the reply path to send this turn."""
        ...

    def pending(self) -> tuple[DiagramResult, ...]:
        """Return the diagrams collected so far WITHOUT clearing them (BOB-037).

        A non-destructive peek the inline-mermaid auto-render reads to dedup against
        a diagram the ``render_diagram`` tool already rendered this turn (matching by
        the :attr:`DiagramResult.source`), before pushing its own. ``drain`` still
        does the clearing send.
        """
        ...

    def drain(self) -> tuple[DiagramResult, ...]:
        """Return + clear the diagrams collected this turn (empty when none)."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Re-scores recall candidates by relevance (an additive quality boost).

    Sits *on top of* :class:`MemoryRecall`: the hybrid recall surfaces a wide
    top-``K`` pool (RRF over keyword + vector), and the reranker re-orders that
    pool by a sharper relevance judgement and trims it to a tight top-``N``. It is
    deliberately ADDITIVE — a recall that cannot reach a reranker (disabled, model
    absent, endpoint down) returns the hybrid order unchanged, so reranking never
    regresses retrieval. Provider-agnostic by design: the first realisation is an
    Ollama-as-scorer (there is no native rerank endpoint — Q1), but the port
    commits only to "query + candidates in, re-ordered (trimmed) candidates out",
    so a dedicated local rerank service swaps in without any consumer change.
    Like embeddings, it runs locally — memory content never leaves the machine.
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[Recalled],
    ) -> list[Recalled]:
        """Return ``candidates`` re-ordered by relevance to ``query`` (best first).

        The result is optionally trimmed to the adapter's configured top-``N``.
        Implementations MUST degrade gracefully: on any unavailability or scoring
        failure they return the input ``candidates`` unchanged (never raise into
        the caller). An empty input yields an empty list.
        """
        ...


@runtime_checkable
class AllowlistStore(Protocol):
    """Durable store for the runtime authorization allowlist (user ids).

    Backs the :class:`bob.application.authz.Authorizer`: ``/authorize`` adds a
    user here so the grant survives a restart. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self) -> set[int]:
        """Return the set of currently allowlisted user ids."""
        ...

    async def add(self, user_id: int) -> None:
        """Add ``user_id`` to the allowlist (idempotent) and persist it."""
        ...

    async def remove(self, user_id: int) -> None:
        """Remove ``user_id`` from the allowlist (idempotent) and persist it."""
        ...


@runtime_checkable
class ProactivityStore(Protocol):
    """Durable per-persona store for Bob's proactivity state (drive engine).

    Round-trips the :class:`bob.domain.proactivity.state.ProactivityState` the
    engine reads on each heartbeat tick and writes after it fires or the owner
    acts: the :class:`SocialEnergy` reservoir, ``last_spoke_at`` /
    ``last_user_msg_at`` markers, and the ``proactivity_enabled`` flag toggled by
    ``/quiet`` / ``/wake``. State is per ``persona_id`` so Bobiverse replicas each
    keep their own. The concrete SQLite-backed adapter arrives in BEAD-03.
    """

    async def load(self, persona_id: str) -> ProactivityState:
        """Return the persisted proactivity state for ``persona_id``."""
        ...

    async def save(self, persona_id: str, state: ProactivityState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior state)."""
        ...


@runtime_checkable
class FascinationStore(Protocol):
    """Durable per-persona store for Bob's current fascination (BOB-020).

    Round-trips the :class:`bob.domain.personality.fascination.Fascination` Bob is
    into right now — the grounded topic, its decaying intensity, and when it took
    hold — so his current passion survives a restart and keeps evolving. State is
    per ``persona_id`` so Bobiverse replicas each keep their own. ``load`` returns
    ``None`` when Bob has no current fascination (a fresh persona, or one whose
    passion was retired and not yet replaced). The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> Fascination | None:
        """Return ``persona_id``'s current fascination, or ``None`` if there is none."""
        ...

    async def save(self, persona_id: str, fascination: Fascination) -> None:
        """Persist ``fascination`` for ``persona_id`` (replacing any prior one)."""
        ...


@runtime_checkable
class FirstImpressionStore(Protocol):
    """Durable per-sender store for Bob's LIGHT first impression (BOB-019).

    Round-trips the :class:`bob.domain.personality.first_impression.FirstImpression`
    Bob forms on first contact with a person — who (``sender_id``), when he first met
    them, and a short impression note — so a returning sender is *recognised*
    ("кажется, мы уже сталкивались"). Keyed by ``sender_id`` it covers owner / known /
    guest / bot alike; this is per-PERSON data (about them), NOT owner-private memory,
    so it is allowed even for a guest. ``load`` returns ``None`` for an unseen sender;
    ``save`` records once and never overwrites a known sender (the impression is formed
    on first contact). The deliberately minimal foundation for multi-party BOB-014, not
    that engine. The concrete SQLite-backed adapter lives in ``bob.infrastructure``.
    """

    async def load(self, sender_id: int) -> FirstImpression | None:
        """Return ``sender_id``'s first impression, or ``None`` if there is none."""
        ...

    async def save(self, impression: FirstImpression) -> None:
        """Record ``impression`` once — a known sender is never overwritten."""
        ...


@runtime_checkable
class RelationshipStore(Protocol):
    """Durable per-sender store for Bob's relationship quality (BOB-014).

    Round-trips the :class:`bob.domain.personality.relationship.Relationship` Bob has
    with each person — the four bounded axes (trust / respect / warmth /
    compatibility) — so a relationship accrued over many turns survives a restart and
    keeps shaping his tone + willingness to compromise. Keyed by ``sender_id`` it
    covers owner / known / guest / bot alike; this is per-PERSON data (about THEM),
    NOT owner-private memory, so it is allowed even for a guest. ``load`` returns
    ``None`` for an unknown sender (Bob has formed no read on them yet). Unlike the
    formed-once :class:`FirstImpressionStore`, ``save`` UPSERTs — a relationship
    evolves, so each turn re-saves the newer state. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure``.
    """

    async def load(self, sender_id: int) -> Relationship | None:
        """Return ``sender_id``'s relationship, or ``None`` if there is none yet."""
        ...

    async def save(self, relationship: Relationship) -> None:
        """Persist ``relationship`` (UPSERT — an evolving relationship is updated)."""
        ...


@runtime_checkable
class NotableReactionStore(Protocol):
    """Light durable store for the most recent "being-received" reaction (BOB-050).

    When someone reacts to one of Bob's messages in a way worth acknowledging, the
    perceiving use-case records a :class:`bob.domain.personality.reaction_effect.NotableReaction`
    here; the rare-aloud hint (BOB-050 .3) reads the latest one so Bob can naturally
    mention being received. Deliberately tiny — a single most-recent record, not a
    log — and per-PERSON about Bob's OWN message, never owner-private material.
    :meth:`latest` returns ``None`` when nothing notable is on record. The concrete
    SQLite-backed adapter lives in ``bob.infrastructure``.
    """

    async def record(self, note: NotableReaction) -> None:
        """Persist ``note`` as the most recent being-received reaction (overwrites)."""
        ...

    async def latest(self) -> NotableReaction | None:
        """Return the most recent recorded reaction, or ``None`` if there is none."""
        ...

    async def clear(self) -> None:
        """Consume the recorded reaction so the rare-aloud hint surfaces it at most once."""
        ...


@runtime_checkable
class ConversationFloorStore(Protocol):
    """Durable per-thread store for the conversation floor (BOB-025).

    Round-trips the :class:`bob.domain.personality.conversation_floor.ConversationFloor`
    — who currently holds the "talking turn" in a thread (Bob / another person / idle),
    when that holder was last confirmed, and the silent-ambient streak — so the
    continuity read survives a restart and across heartbeat ticks. Keyed by the THREAD
    (``chat_id`` + an optional ``thread_id`` for a forum topic; ``None`` for the main
    chat), since the floor is a property of one running exchange, not of a person.
    :meth:`load` returns the default IDLE floor for a thread that has never been seen,
    so the application always has something to read. :meth:`save` UPSERTs — the floor
    advances every turn, so each turn re-saves the newer state. The concrete
    SQLite-backed adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:
        """Return the persisted floor for the thread (default IDLE if unseen)."""
        ...

    async def save(
        self, chat_id: int, thread_id: int | None, floor: ConversationFloor
    ) -> None:
        """Persist ``floor`` for the thread (UPSERT — an advancing floor is updated)."""
        ...


@runtime_checkable
class GoalStore(Protocol):
    """Durable per-persona store for Bob's goal graph (Goal Engine, BOB-015).

    Round-trips the :class:`bob.domain.goals.graph.GoalGraph` — the goals
    (:class:`bob.domain.goals.entities.Goal`) Bob holds and their tasks
    (:class:`bob.domain.goals.entities.Task`, each carrying its ``deps`` and the
    ``needs_external_agency`` flag) — so Bob keeps his goals between sessions. State
    is per ``persona_id`` so Bobiverse replicas each keep their own. :meth:`load`
    returns an empty graph for an unseen persona, so the application always has
    something to read. ``save_goal`` / ``save_task`` UPSERT (a goal/task evolves), and
    ``update_goal_state`` / ``update_task_state`` are atomic state moves the approval
    use-case (.2) and the self-directed tick (.3) drive — keeping the authz-before-
    autonomy machine honest (a tick only ever advances an APPROVED/ACTIVE goal). The
    concrete SQLite-backed adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> GoalGraph:
        """Return the persisted goal graph for ``persona_id`` (empty if unseen)."""
        ...

    async def save_goal(self, persona_id: str, goal: Goal) -> None:
        """Persist ``goal`` for ``persona_id`` (UPSERT — an evolving goal is updated)."""
        ...

    async def save_task(self, persona_id: str, task: Task) -> None:
        """Persist ``task`` for ``persona_id`` (UPSERT — deps + flag round-trip)."""
        ...

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None:
        """Atomically set ``goal_id``'s state (owner approval / tick progress)."""
        ...

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:
        """Atomically set ``task_id``'s state (a tick advances one safe task)."""
        ...


@runtime_checkable
class SelfImprovementStore(Protocol):
    """Durable per-persona store for Bob's self-improvement rules (BOB-028 .1).

    Round-trips the :class:`bob.domain.personality.self_improvement.ImprovementRule`
    set Bob holds — each rule's observation / adjustment, its :class:`Lever` (from the
    hard allowlist), the bounded ``magnitude``, its :class:`RuleState`, ``origin``,
    ``created_at`` and ``evidence`` — so a curated rule (and its approval state)
    survives a restart. State is per ``persona_id`` so Bobiverse replicas each keep
    their own. :meth:`load` returns an empty tuple for an unseen persona, so the
    application always has something to read. ``save_rule`` UPSERTs (a proposed rule
    is persisted, then re-saved as it evolves), and ``update_rule_state`` is an atomic
    state move the manage-rules use-case (.3) drives — keeping authz-before-autonomy
    honest (only owner approval moves PROPOSED -> APPROVED). The concrete SQLite-backed
    adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:
        """Return the persisted rules for ``persona_id`` (empty tuple if unseen)."""
        ...

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:
        """Persist ``rule`` for ``persona_id`` (UPSERT — an evolving rule is updated)."""
        ...

    async def update_rule_state(
        self, persona_id: str, rule_id: str, state: RuleState
    ) -> None:
        """Atomically set ``rule_id``'s state (owner approval / pause / removal)."""
        ...


@runtime_checkable
class SulkStore(Protocol):
    """Durable per-persona store for Bob's обида state (BOB-014 .2b).

    Round-trips the :class:`bob.domain.personality.sulk.SulkState` Bob carries — the
    active flag, the decaying intensity, the low/hostile streak, the entry stamp, and
    the one-shot ``announced`` flag — so an обида (and its recovery progress) survives
    a restart. State is per ``persona_id`` so Bobiverse replicas each keep their own.
    ``load`` returns the fresh, not-sulking default for an unseen persona, so the
    application always has something to read. Crucially this carries NO memory and NO
    soul (anti-Exodus) — only the affect state. The concrete SQLite-backed adapter
    lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> SulkState:
        """Return the persisted обида state for ``persona_id`` (fresh if unseen)."""
        ...

    async def save(self, persona_id: str, state: SulkState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior обида state)."""
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


@runtime_checkable
class ZoneClassifier(Protocol):
    """Classify a topic into a :class:`NegotiationZone` for Bob's stance.

    Decides *who owns the matter at hand* — Bob's own territory of opinions
    (``BOB_PERSONAL``), the user's own business (``USER_DOMAIN``), or jointly
    owned (``SHARED``) — so :class:`Negotiation` can pick how firmly Bob holds.
    The contract is abstract on purpose: the default realisation is a
    deterministic taste/keyword heuristic, but a Tier-0 LLM classifier swaps in
    later without any consumer change.
    """

    def classify(
        self,
        topic: str,
        *,
        taste_verdict: Verdict,
        conviction: float,
    ) -> NegotiationZone:
        """Return the negotiation zone that owns ``topic``."""
        ...


# --- Coding session seam (BOB-039 — «Bob runs Claude Code», gated) ------------


@runtime_checkable
class ClaudeCodeRunner(Protocol):
    """Run the local ``claude`` CLI headless and stream its events (BOB-039 .2).

    The seam the gated coding session delegates execution to: given a ``workdir``
    (the isolated git worktree), a ``prompt`` (the task), and a ``mode`` (``"plan"``
    for plan-mode — a plan with NO edits, the plan gate — or an execute mode such as
    ``"acceptEdits"`` that applies changes inside the worktree), it yields the
    ``--output-format stream-json`` events one by one (each a decoded NDJSON object).
    The contract is deliberately abstract: the live realisation
    (``SubprocessClaudeRunner``) runs ``create_subprocess_exec`` WITHOUT a shell and
    parses NDJSON line-by-line; a deterministic fake yields canned events in tests
    with no subprocess. Events are mapped to narrative lines by the pure
    :func:`bob.domain.coding.narrate.narrate`.
    """

    def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        """Run ``claude`` in ``workdir`` under ``mode``; yield stream-json events."""
        ...


@runtime_checkable
class Worktree(Protocol):
    """Create / remove an isolated git worktree for a coding session (BOB-039 .2).

    The isolation seam: :meth:`create` adds a fresh ``git worktree`` on a new branch
    and returns its path; only TRACKED files are present, so Bob's private data
    (``data/soul/``, ``bob.db*``, ``.env*``, ``config/*`` — all gitignored) is absent
    from the worktree and never reaches Claude Code. :meth:`remove` tears the worktree
    down (the use-case calls it in a ``finally``, so an aborted session cleans up).
    The live realisation (``GitWorktree``) runs git as fixed-form, shell-free
    invocations; a fake substitutes in tests.
    """

    async def create(self, branch: str) -> str:
        """Add an isolated worktree on ``branch`` and return its filesystem path."""
        ...

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        """Stage, commit and push the worktree's changes to the ``bob/<slug>`` branch.

        Bob's DETERMINISTIC integration step (BOB-040): after ``claude`` applies the
        approved plan it does NOT commit (``acceptEdits`` auto-accepts file edits only,
        never git), so the use-case commits + pushes the feature branch before a PR is
        opened. Returns ``True`` when a real commit was pushed, ``False`` when there was
        NOTHING to commit (claude made no change — the use-case then FAILS honestly and
        opens no PR). 🔴 ``branch`` MUST be the validated ``bob/<slug>`` feature branch;
        any other (e.g. ``main``) is refused before git runs — there is no path that can
        push the trunk.
        """
        ...

    async def remove(self, path: str) -> None:
        """Remove the worktree at ``path`` (idempotent cleanup)."""
        ...


@runtime_checkable
class CodingSessionStore(Protocol):
    """Durable store for Bob's gated coding sessions (BOB-039 .1).

    Round-trips the :class:`bob.domain.coding.entities.CodingSession` — its task,
    :class:`~bob.domain.coding.state.CodingSessionState`, branch, worktree path, plan
    text and PR url — so a gated session (and its stage) survives a restart, keeping
    the double gate honest across process boundaries. :meth:`save` UPSERTs on the
    session ``id`` (a session advances, so each step re-saves the newer state);
    :meth:`get` returns ``None`` for an unknown id; :meth:`active` lists the
    non-terminal sessions (so the use-case can find the in-flight one for
    ``/code approve`` / ``/code stop``). The concrete SQLite-backed adapter
    (``SqliteCodingSessionStore``) lives in ``bob.infrastructure.persistence``.
    """

    async def save(self, session: CodingSession) -> None:
        """Persist ``session`` (UPSERT on its ``id`` — an advancing session is updated)."""
        ...

    async def get(self, session_id: str) -> CodingSession | None:
        """Return the session with ``session_id``, or ``None`` if there is none."""
        ...

    async def active(self) -> tuple[CodingSession, ...]:
        """Return the non-terminal sessions (oldest first; empty when none in flight)."""
        ...


@runtime_checkable
class PullRequestOpener(Protocol):
    """Open a pull request for a coding session's branch (BOB-039 .2).

    The PR seam: given the session ``branch``, a ``title`` and a ``body``, it opens a
    PR (the live realisation shells ``gh pr create --base main --head <branch>``,
    shell-free) and returns the PR url. There is DELIBERATELY NO ``merge`` method —
    Bob NEVER merges and never pushes to ``main``: he opens the PR and stops, and the
    owner merges by hand. The absence of a merge path here is part of the safety
    invariant (the use-case physically cannot merge), not an oversight.
    """

    async def open(self, branch: str, title: str, body: str) -> str:
        """Open a PR for ``branch`` and return its url (NEVER merges — owner does)."""
        ...
