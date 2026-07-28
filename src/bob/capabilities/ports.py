# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Capability ports — the GUPPI tool seam and its grounded skills.

The stable :class:`Capability` contract plus the tool-calling provider, the web
skills (search / url-read, BOB-053/054), the local diagram renderer (BOB-035), and
the read-only repo introspector (BOB-017). These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; adapters in
``bob.infrastructure`` realise them. The tool-loop value objects (:class:`ToolCall`,
:class:`ToolCallResult`, …) live here beside the ports that carry them; the only
cross-bucket dependency is :data:`~bob.domain.ports.kernel.LLMMessage`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.ports.kernel import LLMMessage

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


@dataclass(frozen=True, slots=True)
class WebPage:
    """One fetched web page a :class:`UrlReader` extracted (the ``read_url`` payload).

    Provider-agnostic (BOB-054): ``url`` is the FINAL url after any allowed redirects
    (so Bob cites where the content actually came from); ``title`` is the page title
    (``""`` when absent); ``text`` is the extracted, whitespace-collapsed readable body
    (already truncated to the reader's char limit). Immutable so a read page cannot be
    tampered with downstream. The skill (.2) projects this compactly into the tool-loop;
    Bob synthesises the final reply in his own voice — he never confabulates content.
    """

    url: str
    title: str
    text: str


class UrlReadError(Exception):
    """Raised by a :class:`UrlReader` when a page cannot be read (BOB-054).

    The port's failure contract — defined in the domain so the application
    (``read_url``) can catch it WITHOUT importing infrastructure (the hexagon
    forbids application → infrastructure, mirroring :class:`DiagramRenderError`).
    Covers a rejected scheme, a non-2xx status, a disallowed content-type, an
    over-``max_bytes`` body, too many redirects, or empty extracted text — every case
    where Bob must honestly say "couldn't read it" rather than invent content. The
    infra reader (``HttpUrlReader``) re-exports it for adapters.
    """


class SsrfBlockedError(UrlReadError):
    """Raised when a URL resolves to a non-public address (the 🔴 SSRF guard, BOB-054).

    A distinct subtype so the caller can tell a security block from a transient network
    failure: a block is DETERMINISTIC and must NOT be retried, just honestly refused (the
    ``read_url`` skill short-circuits the bounded retry for exactly this class).
    """


class DiagramRenderError(Exception):
    """Raised by a :class:`DiagramRenderer` when it cannot render (BOB-035).

    The port's failure contract — defined in the domain so the application
    (``render_diagram``) can catch it WITHOUT importing infrastructure (the hexagon
    forbids application → infrastructure). An adapter
    (:class:`~bob.capabilities.adapters.diagrams.mmdc_renderer.SubprocessMmdcRenderer`)
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

    The tool-aware sibling of :class:`~bob.domain.ports.kernel.LLMProvider`: given the
    conversation and a manifest of tool definitions, it returns a
    :class:`ToolCallResult` (final text, or the tool calls the model requested).
    Adapters realise this over a native OpenAI ``tools`` round-trip or a prompt-protocol
    fallback.
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
class UrlReader(Protocol):
    """Open a concrete URL and return its extracted readable content (BOB-054).

    The provider-agnostic seam the ``read_url`` skill delegates to: given a ``url``,
    fetch the page and return a :class:`WebPage` (final url + title + extracted text).
    The first realisation is ``HttpUrlReader`` (aiohttp + a 🔴 SSRF guard + stdlib
    ``html.parser`` extraction), but a headless-render or paid-plugin reader swaps in
    behind the same port without any skill change. An implementation RAISES on any
    failure — a blocked (SSRF) address, a network error, a non-2xx, a disallowed
    content-type, or empty extracted text — so the caller (.2) owns fault-tolerance and
    Bob never confabulates what a page said. It must NEVER return a page it could not
    genuinely read.
    """

    async def read(self, url: str) -> WebPage:
        """Fetch ``url`` and return its extracted content (raises on failure/block)."""
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
    :class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard` before opening a
    file and sanitises output, so a denied path (SOUL / DB / ``.env`` / ``config``)
    can never be read. The contract is deliberately abstract — the live realisation
    is the subprocess adapter in ``bob.capabilities.adapters.introspection``; a deterministic
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
class DiagramRenderer(Protocol):
    """Render mermaid source to a PNG image — the LOCAL diagram-render seam (BOB-035).

    The pure abstraction the ``render_diagram`` capability delegates to: given the
    mermaid source the user (or Bob) wrote, return the rendered PNG bytes. The
    realisation runs strictly LOCALLY (privacy — diagram source never leaves the
    machine): the first adapter
    (:class:`~bob.capabilities.adapters.diagrams.mmdc_renderer.SubprocessMmdcRenderer`)
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
