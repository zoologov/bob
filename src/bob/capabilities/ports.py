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
cross-bucket dependency is :data:`~bob.kernel.ports.ToolLoopMessage`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.kernel.ports import ToolLoopMessage

# An OpenAI-shaped tool definition (``{"type": "function", "function": {...}}``),
# as emitted by the CapabilityRegistry manifest and sent to the LLM as ``tools``.
type ToolDefinition = Mapping[str, object]

# A capability's permission seam: "safe" runs straight through; "confirm" marks a
# capability a HUMAN must clear before GUPPI executes it. Read by the autonomous
# boundary (:class:`~bob.capabilities.usecases.registry.SafeCapabilityDispatcher`),
# which refuses a "confirm" capability on the self-directed tick — there is nobody
# there to ask (BOB-090.B-fix: the declaration used to be read by no one at all).
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


@dataclass(frozen=True)
class ArchitectureDiagram:
    """A diagram of Bob's own architecture: the mermaid SOURCE plus which form it is.

    What the read-only ``beadloom graph`` read returns (BOB-091.1). ``mermaid`` is the
    diagram SOURCE, deliberately not a picture: Bob explains what the diagram shows in
    his own words AND hands the same source to ``render_diagram`` for the image, instead
    of silently dropping a PNG on the owner.

    ``requested`` is the form that was ASKED for and ``form`` the one actually drawn —
    they differ when the detailed view had nothing to show (a ``--scope`` on a graph LEAF
    prints an empty diagram, so the node's links are drawn instead). Carrying both is
    what keeps the answer honest: Bob can say "внутренностей там нет, вот связи" rather
    than passing one view off as the other. Values are the pure planner's form kinds
    (``overview`` / ``node`` / ``components``).
    """

    mermaid: str
    form: str
    requested: str


@dataclass(frozen=True)
class ProjectHealth:
    """One read-only project-health report: WHICH report it is, and its digest.

    What the read-only beadloom health reads return (BOB-091.2). ``check`` is the
    canonical report name (``status`` / ``prime`` / ``doctor`` / ``sync-check`` / ``lint``
    / ``diff``) — carried so Bob can say WHICH command he actually ran instead of
    presenting one report's verdict as another's, which matters most where a paraphrase
    was resolved ("как с доками?" → ``sync-check``). ``report`` is the already-condensed
    answer: the terminal decoration, the 585 fresh doc↔code pairs and the 224-line rule
    list never reach a chat message.
    """

    check: str
    report: str


@runtime_checkable
class Capability(Protocol):
    """A single thing GUPPI can do for Bob — the stable capability seam.

    This is the contract, NOT the plugin machinery: a capability names itself,
    describes itself, advertises a JSON-Schema for its arguments, declares a
    ``permission`` (``"safe"`` runs straight through; ``"confirm"`` says a human must
    clear it, so the autonomous boundary refuses it), and ``execute``s against decoded
    arguments. New skills register an object against this contract; consumers never
    change — and a new skill is gated by what it declares about ITSELF.
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
        """Approval seam: ``"safe"`` runs unattended; ``"confirm"`` needs a human."""
        ...

    async def execute(self, args: Mapping[str, object]) -> object:
        """Run the capability against ``args`` and return its result."""
        ...


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
class OutboundMessenger(Protocol):
    """Send one message to an EXPLICIT address — chat plus forum topic (BOB-090.B1).

    The seam the ``send_to_chat`` skill delegates to, so the skill never touches a bot.
    The address is passed per call, and both halves matter: in a forum group a
    ``topic_id`` of ``None`` is not «the chat», it is the General topic, so the exact
    address is what makes «напиши в нашу группу» land where people actually talk.

    ``topic_id`` is passed through as-is and never invented (``None`` = «топика нет»: a
    DM, or a group without forum topics). The first realisation rides the existing rich
    markdown send (no new transport in this epic). An implementation may raise on a
    transport failure — the caller decides what to tell Bob.
    """

    async def send(self, *, chat_id: int, topic_id: int | None, markdown: str) -> None:
        """Post ``markdown`` into ``chat_id`` / ``topic_id`` (raises on failure)."""
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

    async def architecture_diagram(
        self,
        ref: str | None = None,
        *,
        depth: int | None = None,
        internals_of: str | None = None,
    ) -> ArchitectureDiagram:
        """Return the mermaid SOURCE of Bob's architecture graph (read-only, BOB-091).

        Three shapes, most specific first: ``internals_of`` — the C4 components inside
        one container; ``ref`` — that node's neighbourhood, optionally limited by
        ``depth``; neither — the whole-system overview. The implementation runs
        ``beadloom graph`` as a FIXED set of argv forms with each slot validated (a
        ref-shaped token, a clamped depth), so no flag — another project, another
        format, a write subcommand — is expressible; a non-ref value is refused
        (:class:`ValueError`) and never executed. When the detailed form draws NOTHING
        (a ``--scope`` on a graph leaf) the implementation falls back to the simpler
        form and reports it in :attr:`ArchitectureDiagram.form`, so the caller can stay
        honest about which view it got. The source is returned, not an image: rendering
        is the diagram port's job.
        """
        ...

    async def impact(self, ref: str) -> str:
        """Return what ``ref`` depends on and what depends on it (``beadloom why``).

        The answer to "что сломается, если тронуть X". ``ref`` is validated to a graph
        ref-id before exec (a flag / path / metacharacter is refused with
        :class:`ValueError`, never executed), and the CLI's Rich panel + ASCII tree are
        CONDENSED to the subject, its direct dependencies, its direct dependents and an
        honest count of what lies deeper — a chat answer, not a terminal screenshot. An
        unknown ref yields an empty string (the caller answers honestly), never a guess.
        """
        ...

    async def project_health(
        self, check: str, *, since: str | None = None
    ) -> ProjectHealth:
        """Return one read-only project-health report, condensed (BOB-091.2).

        ``check`` names the report from a CLOSED list — ``status`` (index statistics),
        ``prime`` (compact project context), ``doctor`` (graph integrity), ``sync-check``
        (doc↔code freshness), ``lint`` (architecture boundaries), ``diff`` (graph changes
        since a git ref) — and a paraphrase resolves to one of them; anything else is
        refused (:class:`ValueError`) rather than forwarded, because the SAME CLI holds the
        write subcommands. ``since`` applies to ``diff`` alone and is validated to a strict
        git-ref shape before exec.

        🔴 A non-zero exit code on this path is a RESULT, not a failure: ``lint`` exits 1
        on a violation, ``sync-check`` 2 on a stale pair, ``diff`` 1 on a change. The
        implementation must answer with the verdict ("доки отстали") and never with "не
        смог посмотреть". The reports are CONDENSED — the human ones lose their terminal
        frames, the 585 fresh doc↔code pairs become a count, and the machine-porcelain
        lint tuples become readable lines.
        """
        ...

    async def read_file(self, path: str, *, max_lines: int) -> str:
        """Return up to ``max_lines`` of ``path`` — guard-checked BEFORE opening.

        Raises / returns a refusal (implementation-defined, never a disk read) when
        the privacy guard denies ``path``; otherwise the text is sanitised before
        return.
        """
        ...

    async def list_dir(self, path: str) -> str:
        """Return the entries of directory ``path`` — guard-checked, NON-recursive.

        Lists the immediate children of the repo-relative (or in-repo absolute)
        directory ``path`` with each entry's name, kind (``file``/``dir``) and size,
        sorted for determinism. A path escaping the repo is refused (never listed);
        a missing path or a non-directory yields an honest message rather than a
        fabricated listing. Output is sanitised before return.
        """
        ...

    async def find_file(self, pattern: str) -> str:
        """Return repo-relative paths matching glob ``pattern`` across the repo tree.

        Walks the repo tree from the root and returns the paths whose name/glob
        matches ``pattern`` (e.g. ``*.py`` or ``nodes.yml``), one per line, capped at
        a fixed maximum with an honest truncation note. ``.git/`` and symlinks that
        escape the repo are skipped; an empty result is reported honestly. Output is
        sanitised before return.
        """
        ...

    async def list_tasks(self, query: str) -> str:
        """Return tracker state for ``query`` (``bd`` ready/show/list/search, read-only).

        Routes a task id to ``bd show``, a listing request (open / in-progress /
        closed / all) to the matching ``bd list``, an epic key or a word to a title
        ``bd search`` that INCLUDES closed tasks (an epic key lives in titles, not in
        ids), and an empty/"ready" query to the ready queue. A long search result
        comes back digested, and tooling-noise tail lines are stripped.
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

    async def recent_commits(self, count: int) -> str:
        """Return the last ``count`` commits repo-wide (read-only git log, BOB-081).

        ``count`` is clamped into a bounded range by the implementation so history is
        never unbounded; the git invocation is a FIXED ``log --oneline -n <N>`` form
        with no path and no ``--grep``. Output is sanitised and truncated like the
        other reads.
        """
        ...

    async def task_comments(self, bead_id: str) -> str:
        """Return the tracker comments/checkpoints for ``bead_id`` (``bd comments``).

        The id is validated to a strict bead-key shape before it reaches the
        subprocess — a flag or an injection-shaped value is refused (never executed).
        Read-only: the implementation never writes to the tracker.
        """
        ...

    async def show_task(self, bead_id: str) -> str:
        """Return the details of ``bead_id`` (``bd show <id>``, read-only).

        The id is validated to a strict bead-key shape before exec, so a
        flag/injection value is refused (never executed). A key the tracker does not
        know as an IDENTIFIER (an epic key such as ``BOB-087`` lives only in titles)
        is retried as a read-only title search instead of answering "no such task".
        """
        ...

    async def tasks_by_status(self, status: str | None) -> str:
        """List tracker tasks, optionally filtered by ``status`` (``bd list``).

        ``status`` is normalised to the stored-status enum (accepting a Russian
        synonym); an unknown or ``None`` status yields the unfiltered list rather than
        a guessed filter. The resulting ``--status`` value is always an allowlisted
        enum. Read-only; output is sanitised and truncated.
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
