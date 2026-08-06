# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""SubprocessRepoIntrospector — read-only self-introspection over the local repo.

Realises :class:`bob.capabilities.ports.RepoIntrospector` (BOB-017 Phase A). Two seams:

* **CLI introspection** — ``beadloom`` (``ctx`` / ``graph`` / ``why`` / ``search``)
  and ``bd`` (``ready`` / ``show`` / ``list`` / ``comments`` / ``search``) run via
  ``asyncio.create_subprocess_exec`` (NEVER a shell, so no metacharacter injection)
  against a FIXED allowlist of read-only subcommands. Anything off the allowlist — a
  write subcommand, an unknown binary, a flag-looking argument that could smuggle
  behaviour — is refused with :class:`DisallowedCommandError` and never executed. The
  flag-bearing exceptions are controlled FIXED FORMS, never raw passthrough: ``bd list
  --status <enum>`` (one stored-status enum value from a fixed set) and ``bd search
  <term> --status all`` (the term must be exactly what the pure sanitiser produces);
  a status outside the enum, another flag, or a flag-shaped term is still refused.
  Free-text questions ground via ``beadloom search`` (``ctx`` needs an exact ref, with
  a ``ctx``→``search`` fallback on empty); trailing tooling-noise lines (status legend
  / Tip / ``--limit`` hint) are stripped. Output is bounded by a char cap and run
  through the privacy sanitiser; each run has a hard timeout. 🔴 A read that CONDENSES its
  output does so BEFORE that cap (:meth:`_run`'s ``condense``) — otherwise the digest
  counts only what fitted and states a wrong number confidently (BOB-091.2).
* **Architecture graph reads (BOB-091.1)** — ``graph`` and ``why`` were allowlisted from
  the start but DEAD (no port method reached them), so Bob could neither draw his
  architecture nor answer "что сломается, если тронуть memory". :meth:`architecture_diagram`
  runs one of the THREE fixed ``graph`` forms planned by the pure
  :func:`~bob.capabilities.introspection.graph_form.plan_graph_form` — the bare overview,
  ``<ref> [--depth <N>]``, or the C4-components view of one ``--scope`` — re-checked here
  before exec, so ``--project`` (another repo), ``--json``, another format or a write
  subcommand stay INEXPRESSIBLE; a form that drew nothing degrades to its fallback and
  says so. :meth:`impact` runs ``why <ref>`` and condenses the Rich panel + ASCII tree
  through :func:`~bob.capabilities.introspection.impact_digest.digest_impact`.
* **Project-health reads (BOB-091.2)** — the REST of the read-only beadloom behind ONE
  port method: :meth:`project_health` runs the fixed form the pure
  :func:`~bob.capabilities.introspection.health_form.plan_health_form` picked for a report
  from a CLOSED list (``status`` / ``prime`` / ``doctor`` / ``sync-check`` / ``lint`` /
  ``diff --since <git-ref>``) and condenses it with
  :func:`~bob.capabilities.introspection.health_digest.digest_health`. 🔴 ``lint`` carries
  ``--no-reindex`` because a plain ``beadloom lint`` REINDEXES, i.e. WRITES the index, and
  ``--strict`` because otherwise its exit code means nothing; the empty forms are what make
  ``prime --update`` (it rewrites ``AGENTS.md``) inexpressible. 🔴 A non-zero exit status on
  this path is a RESULT (``lint`` 1 = violation, ``sync-check`` 2 = stale, ``diff`` 1 =
  changed): the runner never inspects ``returncode``, so Bob answers "доки отстали" instead
  of "не смог посмотреть".
* **Tracker reads (BOB-090.A)** — a tracker question is PLANNED by the pure
  :func:`~bob.capabilities.introspection.tracker_intent.plan_tracker_query` and only
  executed here. An id that ``bd show`` cannot resolve retries as a title SEARCH
  (in ``bd`` the identifier is ``bob-abk`` while the epic key ``BOB-087`` lives only
  in the TITLE — and, being closed, is excluded from ``bd search`` unless
  ``--status all`` is passed); a long search result is condensed by
  :func:`~bob.capabilities.introspection.tracker_digest.digest_search_results` instead
  of dumping forty lines into a chat.
* **File reads** — :meth:`read_file` consults the pure
  :class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard` BEFORE opening any
  file: a denied path (SOUL / ``bob.db`` / ``.env`` / ``config``) raises
  :class:`DeniedPathError` without a disk touch. Allowed content is line-capped and
  sanitised before return.

The subprocess boundary is injected as a ``runner`` callable so tests substitute a
deterministic fake and never spawn a process. The default runner uses
``create_subprocess_exec`` with the timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bob.capabilities.introspection.dev_query import (
    clamp_commit_count,
    normalize_status,
    sanitize_search_term,
    validate_bead_id,
)
from bob.capabilities.introspection.graph_form import (
    MAX_GRAPH_DEPTH,
    diagram_carries_nodes,
    is_graph_ref,
    plan_graph_form,
    validate_graph_ref,
)
from bob.capabilities.introspection.health_digest import digest_health
from bob.capabilities.introspection.health_form import (
    is_git_ref,
    plan_health_form,
)
from bob.capabilities.introspection.impact_digest import digest_impact
from bob.capabilities.introspection.privacy_guard import ALLOWED_ROOTS
from bob.capabilities.introspection.tracker_digest import digest_search_results
from bob.capabilities.introspection.tracker_intent import plan_tracker_query
from bob.capabilities.ports import ArchitectureDiagram, ProjectHealth

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from bob.capabilities.introspection.privacy_guard import PrivacyGuard

# Repo-navigation bounds (BOB-067). ``.git`` is skipped when walking the tree: first for
# practicality (a huge binary store that would flood a match list), and since bob-a6b.13
# also for privacy — git's own config carries the credentialed remote URL, so the pure
# guard refuses that subtree too and this walk would only be throwing away paths the
# guard rejects one line later. ``find_file`` caps its result list so a broad glob never
# floods the model, with an honest truncation note appended.
_GIT_DIR = ".git"
_FIND_FILE_MAX_RESULTS = 200

# Fixed allowlist of read-only subcommands, keyed by binary. NOTHING else runs.
_BEADLOOM_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "ctx",
        "graph",
        "why",
        "search",
        # BOB-091.2 — the rest of the READ-ONLY beadloom, each behind one fixed form.
        "status",
        "prime",
        "doctor",
        "sync-check",
        "lint",
        "diff",
    }
)
_BD_SUBCOMMANDS: frozenset[str] = frozenset(
    {"ready", "show", "list", "comments", "search"}
)
# git is allowed ONLY as ``git log`` in the fixed forms validated below — never
# ``show`` / ``diff`` / ``blame`` / ``cat-file`` / a write subcommand.
_GIT_SUBCOMMANDS: frozenset[str] = frozenset({"log"})

# The ONLY argv shape allowed after ``bd list``: the literal ``--status`` flag paired
# with one stored-status enum value. Modelled as a fixed allowlist (not raw flag
# passthrough) so the read-only "no arbitrary args/flags" invariant still holds — a
# status token outside this set, or any other flag, is refused before execution.
_BD_LIST_STATUSES: frozenset[str] = frozenset(
    {"open", "in_progress", "blocked", "deferred", "closed"}
)
# The exact, fully-resolved arg tuples permitted after ``bd list`` — an allowlist of
# ``("--status", <enum>)`` pairs, NOT raw flag passthrough. Membership-checked, so a
# status outside the enum or any other flag never reaches the subprocess.
_BD_LIST_ARG_FORMS: frozenset[tuple[str, ...]] = frozenset(
    ("--status", status) for status in _BD_LIST_STATUSES
)

# --- bd search fixed form (BOB-090.A) -----------------------------------------
# ``bd search`` excludes CLOSED issues by default, so a question about a finished epic
# ("расскажи про BOB-087") finds NOTHING without this tail — the exact reason Bob told
# the owner the epic did not exist. It is modelled the same way as ``bd list``: a
# FIXED tail, not a flag the caller may choose, so no other search flag is expressible.
_BD_SEARCH_TAIL_FORM: tuple[str, ...] = ("--status", "all")
# Exact argv length of the only permitted search shape: ``<term> --status all``.
_BD_SEARCH_FORM_LEN = 3

# --- beadloom graph / why fixed forms (BOB-091.1) -----------------------------
# ``graph`` and ``why`` were allowlisted in BOB-017 but DEAD (no port method reached
# them). Giving them a caller means giving the model argv — and ``beadloom graph``
# accepts ``--project`` (another repo!), ``--json`` and other formats, while the CLI as
# a whole has WRITE subcommands. So, exactly like ``_BD_LIST_ARG_FORMS``, only a small
# set of FIXED SHAPES passes, each dynamic slot validated: the bare overview, one
# ref (optionally with a bounded ``--depth``), and the C4-components view of one scope.
# The shapes are planned by the pure
# :func:`~bob.capabilities.introspection.graph_form.plan_graph_form` and RE-CHECKED here
# before exec, so a caller that skipped the planner cannot widen them.
_GRAPH_C4_FORM_PREFIX: tuple[str, ...] = (
    "--format",
    "c4",
    "--level",
    "component",
    "--scope",
)
# Exact argv lengths of the permitted ``graph`` forms (after the subcommand): the bare
# overview (0), one ref (1), ``<ref> --depth <N>`` (3), and the C4 form (6).
_GRAPH_OVERVIEW_FORM_LEN = 0
_GRAPH_NODE_FORM_LEN = 1
_GRAPH_DEPTH_FORM_LEN = 3
_GRAPH_C4_FORM_LEN = 6
# ``why`` takes exactly ONE ref — no flag, no second token.
_WHY_FORM_LEN = 1

# --- beadloom health fixed forms (BOB-091.2) ----------------------------------
# The rest of the read-only beadloom, one FIXED arg tuple per subcommand — re-declared
# here (not imported from the planner) so the exec gate is an INDEPENDENT re-check: a
# caller that skips the planner still cannot widen a form.
#
# 🔴 ``lint`` carries ``--no-reindex`` because a plain ``beadloom lint`` REINDEXES first,
# i.e. WRITES the index (measured on this repo: the db's content hash changes). Bob is
# read-only, so the flag is part of the invariant; ``--strict`` is what makes the exit
# code mean "error-level violations" (plain ``lint`` exits 0 even when a rule is broken).
# 🔴 The empty tuples are what makes ``prime --update`` — which REWRITES ``AGENTS.md`` —
# and ``--project <another repo>`` / ``--json`` structurally inexpressible.
_BEADLOOM_HEALTH_FORMS: dict[str, tuple[str, ...]] = {
    "status": (),
    "prime": (),
    "doctor": (),
    "sync-check": (),
    "lint": ("--no-reindex", "--strict"),
}
# ``diff`` is the only health form with a slot: ``--since <git-ref>``.
_DIFF_SINCE_FLAG = "--since"
_DIFF_FORM_LEN = 2
# The health subcommands whose args go through the form gate above (``diff`` included:
# its shape is checked separately because it carries the ref slot).
_HEALTH_SUBCOMMANDS: frozenset[str] = frozenset({*_BEADLOOM_HEALTH_FORMS, "diff"})

# --- git fixed-form allowlist (BOB-038) ---------------------------------------
# git needs flags (``--oneline`` / ``--grep=``), which the generic flag-reject would
# refuse — so, exactly like ``_BD_LIST_ARG_FORMS``, git is permitted ONLY as a small
# set of FIXED ``git log`` invocation SHAPES whose dynamic slots (path, count, bead
# key) are each validated. Any other shape, flag, or subcommand is refused before
# exec, so the read-only invariant cannot be talked around by the model.

# A strict bead key: an epic key ``BOB-37`` or a graph node-id ``bob-4be.1``. Only a
# string of this shape may appear after ``--grep=``.
_GIT_BEAD_KEY_RE = re.compile(r"^(?:BOB-\d+|bob-[a-z0-9.]+)$")

# Hard upper bound on ``git log -n <N>`` so history is always bounded.
_GIT_MAX_LOG_COUNT = 1000
# Default commit count for a path history (the bounded ``-n`` slot).
_DEFAULT_HISTORY_COUNT = 50

# Exact argv lengths of the permitted ``git log`` forms (after the subcommand):
# ``--grep=<key> --oneline`` (2), the repo-wide ``--oneline -n <N>`` (3),
# ``--oneline -- <path>`` (3), and the bounded ``--oneline -n <N> -- <path>`` (5).
# Named so the shape checks carry no magic value. The two length-3 forms are
# disambiguated by their middle token (``-n`` for repo-wide vs. ``--`` for a path).
_GIT_GREP_FORM_LEN = 2
_GIT_REPO_WIDE_FORM_LEN = 3
_GIT_PATH_FORM_LEN = 3
_GIT_BOUNDED_PATH_FORM_LEN = 5

# Default resource bounds (overridable via the constructor).
_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_OUTPUT_CHARS = 20_000

_TRUNCATION_MARKER = "\n…[truncated]"

# A graph ref-id is a node-id shape (e.g. ``bob-1av``) or a single source filename
# (``<word>.py`` / ``<word>.md``) — always one whitespace-free token. Anything else is
# treated as a free-text question and grounded via ``beadloom search`` instead of
# ``ctx`` (which needs an EXACT ref). Deterministic, no I/O.
_REF_ID_RE = re.compile(r"^(?:[a-z][a-z0-9]*-[a-z0-9.]+|[\w.-]+\.(?:py|md|ya?ml))$")

# bd/beadloom append a status legend / setup tip / ``--limit`` hint to human output.
# These TRAILING tooling lines are noise for Bob (he must not riff on them), so they
# are stripped before the result is returned. Matched per-line, conservatively.
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:💡|Tip:|Status:\s*○|Showing\s+\d+\s+issues|Use\s+--limit)"
)


def _is_ref_id(query: str) -> bool:
    """Whether ``query`` is an exact graph/tracker ref-id (vs. a free-text question)."""
    token = query.strip()
    if not token or " " in token:
        return False
    return bool(_REF_ID_RE.match(token))


def _is_allowed_bd_search_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is the ``<term> --status all`` fixed form for ``bd search``.

    The tail is compared against the fixed tuple (no other flag is expressible), and
    the term slot must be EXACTLY what :func:`sanitize_search_term` produces — the
    sanitiser is idempotent, so re-running it here is a cheap re-assertion that the
    value cannot be read as a flag (🔴 BOB-087.D2), carries no control character, and
    is length-bounded. Anything else is refused before exec.
    """
    if len(args) != _BD_SEARCH_FORM_LEN:
        return False
    term = args[0]
    if args[1:] != _BD_SEARCH_TAIL_FORM:
        return False
    return sanitize_search_term(term) == term


def _is_valid_graph_depth(depth: str) -> bool:
    """Whether ``depth`` is a positive integer inside the planner's bounded window."""
    return depth.isdigit() and 0 < int(depth) <= MAX_GRAPH_DEPTH


def _is_allowed_graph_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is one of the three permitted ``beadloom graph`` shapes.

    The overview (no args), one ref, ``<ref> --depth <N>`` with the count inside the
    bounded window, or the C4-components form whose FIXED prefix is compared against the
    stored tuple and whose scope slot must be a graph ref. Every other shape — another
    flag, another format/level, a second ref, an out-of-range depth, a non-ref token — is
    refused before exec.
    """
    if len(args) == _GRAPH_OVERVIEW_FORM_LEN:
        return True
    if len(args) == _GRAPH_NODE_FORM_LEN:
        return is_graph_ref(args[0])
    if len(args) == _GRAPH_DEPTH_FORM_LEN:
        ref, flag, depth = args
        return is_graph_ref(ref) and flag == "--depth" and _is_valid_graph_depth(depth)
    if len(args) == _GRAPH_C4_FORM_LEN:
        return args[:-1] == _GRAPH_C4_FORM_PREFIX and is_graph_ref(args[-1])
    return False


def _is_allowed_why_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is the ``beadloom why <ref>`` fixed form (one validated ref)."""
    return len(args) == _WHY_FORM_LEN and is_graph_ref(args[0])


def _is_allowed_health_form(subcommand: str, args: tuple[str, ...]) -> bool:
    """Whether ``args`` is the fixed read-only form of health ``subcommand``.

    ``diff`` is compared shape-wise (the literal ``--since`` plus a validated git ref);
    every other health read is compared against its EXACT stored tuple, so an extra flag,
    another output format, another project, or the reindexing ``lint`` shape is refused
    before exec.
    """
    if subcommand == "diff":
        return (
            len(args) == _DIFF_FORM_LEN
            and args[0] == _DIFF_SINCE_FLAG
            and is_git_ref(args[1])
        )
    return args == _BEADLOOM_HEALTH_FORMS.get(subcommand)


def _strip_noise_tail(text: str) -> str:
    """Drop trailing tooling-noise lines (status legend / Tip / ``--limit`` hint).

    Only the *tail* is trimmed: scanning upward, blank lines and noise lines are
    removed until the first line of real content, so content that merely follows a
    legend is never touched. Interior content is left intact.
    """
    lines = text.splitlines()
    while lines and (not lines[-1].strip() or _NOISE_LINE_RE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


class IntrospectionError(Exception):
    """Base for read-only introspection failures."""


class DisallowedCommandError(IntrospectionError):
    """A command/subcommand/argument outside the read-only allowlist was refused."""


class DeniedPathError(IntrospectionError):
    """A file read was refused by the privacy guard before any disk access."""


class _CommandRunner(Protocol):
    """The injected subprocess boundary: run ``argv`` with a timeout, return stdout."""

    async def __call__(self, argv: list[str], *, timeout: float) -> str: ...


def _looks_like_flag(arg: str) -> bool:
    """Whether ``arg`` resembles a CLI flag (which we never forward)."""
    return arg.startswith("-")


def _is_bead_key(token: str) -> bool:
    """Whether ``token`` is a strict bead/node key (``BOB-37`` / ``bob-4be.1``)."""
    return bool(_GIT_BEAD_KEY_RE.match(token))


def _is_safe_git_path(path: str) -> bool:
    """Whether ``path`` is a safe repo-relative pathspec for ``git log``.

    Refuses an empty value, a flag-looking token, an absolute path, and any ``..``
    segment — so the pathspec stays inside the repo and can never smuggle a flag.
    """
    if not path or _looks_like_flag(path):
        return False
    candidate = Path(path)
    if candidate.is_absolute():
        return False
    return ".." not in candidate.parts


def _is_valid_log_count(count: str) -> bool:
    """Whether ``count`` is a positive, bounded integer for ``git log -n``."""
    return count.isdigit() and 0 < int(count) <= _GIT_MAX_LOG_COUNT


def _is_allowed_git_grep_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is the ``--grep=<bead-key> --oneline`` fixed form."""
    if len(args) != _GIT_GREP_FORM_LEN or args[1] != "--oneline":
        return False
    prefix = "--grep="
    if not args[0].startswith(prefix):
        return False
    return _is_bead_key(args[0][len(prefix) :])


def _is_allowed_git_repo_wide_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is the repo-wide ``--oneline -n <N>`` fixed form (BOB-081).

    A bounded recent-commits listing with NO path and NO ``--grep``: the count slot
    is validated as a positive bounded integer. Distinguished from the path form of
    the same length by the ``-n`` middle token (vs. ``--``).
    """
    if len(args) != _GIT_REPO_WIDE_FORM_LEN:
        return False
    oneline, dash_n, count = args
    return oneline == "--oneline" and dash_n == "-n" and _is_valid_log_count(count)


def _is_allowed_git_path_form(args: tuple[str, ...]) -> bool:
    """Whether ``args`` is an ``--oneline [-n N] -- <path>`` fixed form.

    Accepts both the plain ``--oneline -- <path>`` and the bounded
    ``--oneline -n <N> -- <path>`` shapes; the path slot is validated as a safe
    repo-relative pathspec and the count slot as a positive bounded integer.
    """
    if len(args) == _GIT_PATH_FORM_LEN:
        oneline, separator, path = args
        return oneline == "--oneline" and separator == "--" and _is_safe_git_path(path)
    if len(args) == _GIT_BOUNDED_PATH_FORM_LEN:
        oneline, dash_n, count, separator, path = args
        return (
            oneline == "--oneline"
            and dash_n == "-n"
            and _is_valid_log_count(count)
            and separator == "--"
            and _is_safe_git_path(path)
        )
    return False


def _format_dir_entry(entry: os.DirEntry[str]) -> str:
    """Render one directory entry as ``name<TAB>kind[<TAB>size]`` for ``list_dir``.

    A directory is shown as ``name/<TAB>dir``; a file as ``name<TAB>file<TAB>size``
    (bytes). Symlinks are classified by their own type (``follow_symlinks=False``) so
    a listing never chases a link, and a stat failure degrades to a zero size rather
    than crashing the listing.
    """
    if entry.is_dir(follow_symlinks=False):
        return f"{entry.name}/\tdir"
    try:
        size = entry.stat(follow_symlinks=False).st_size
    except OSError:
        size = 0
    return f"{entry.name}\tfile\t{size}"


class SubprocessRepoIntrospector:
    """Read-only RepoIntrospector over local ``beadloom`` / ``bd`` + guarded files."""

    def __init__(
        self,
        guard: PrivacyGuard,
        *,
        runner: _CommandRunner | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT_CHARS,
        beadloom_bin: str = "beadloom",
        bd_bin: str = "bd",
        git_bin: str = "git",
        history_max_commits: int = _DEFAULT_HISTORY_COUNT,
    ) -> None:
        self._guard = guard
        self._runner: _CommandRunner = runner or _ExecRunner()
        self._timeout = timeout
        self._max_output_chars = max_output_chars
        self._beadloom_bin = beadloom_bin
        self._bd_bin = bd_bin
        self._git_bin = git_bin
        self._history_max_commits = history_max_commits
        # Map the canonical binary name -> (configured path, allowed subcommands).
        self._allow: dict[str, tuple[str, frozenset[str]]] = {
            "beadloom": (beadloom_bin, _BEADLOOM_SUBCOMMANDS),
            "bd": (bd_bin, _BD_SUBCOMMANDS),
            "git": (git_bin, _GIT_SUBCOMMANDS),
        }

    # --- RepoIntrospector port ------------------------------------------------

    async def architecture_context(self, query: str) -> str:
        """Ground ``query`` in the architecture graph (read-only, always grounded).

        Free text (a natural question) routes to ``beadloom search`` so it grounds
        without an exact ref. An exact graph ref-id routes to ``beadloom ctx``; when
        ``ctx`` cannot resolve it (empty), the query is retried through ``search`` so
        natural questions never fall back to ungrounded model knowledge.
        """
        if not _is_ref_id(query):
            return await self._run("beadloom", "search", query)
        ctx = await self._run("beadloom", "ctx", query)
        if ctx.strip():
            return ctx
        return await self._run("beadloom", "search", query)

    async def search_code(self, query: str) -> str:
        """Run ``beadloom search <query>`` (read-only FTS over nodes/docs)."""
        return await self._run("beadloom", "search", query)

    async def architecture_diagram(
        self,
        ref: str | None = None,
        *,
        depth: int | None = None,
        internals_of: str | None = None,
    ) -> ArchitectureDiagram:
        """Return the mermaid source of the architecture graph (BOB-091.1).

        The DECISION — which of the three allowed forms answers the ask — belongs to the
        pure :func:`plan_graph_form`; this method only executes it and applies the one
        honest degradation: a form that drew NOTHING (the live ``C4Container``-only output
        of a ``--scope`` on a graph leaf) is re-asked as its simpler fallback, and the
        result reports which form was actually drawn so the caller never presents links
        as internals. A non-ref value raises :class:`ValueError` before any exec.
        """
        form = plan_graph_form(ref, depth=depth, internals_of=internals_of)
        source = await self._run("beadloom", "graph", *form.args)
        fallback = form.fallback
        if fallback is None or diagram_carries_nodes(source):
            return ArchitectureDiagram(
                mermaid=source, form=form.kind, requested=form.kind
            )
        simpler = await self._run("beadloom", "graph", *fallback.args)
        return ArchitectureDiagram(
            mermaid=simpler, form=fallback.kind, requested=form.kind
        )

    async def impact(self, ref: str) -> str:
        """Return the CONDENSED ``beadloom why <ref>`` impact analysis (BOB-091.1).

        ``ref`` goes through :func:`validate_graph_ref` first, so a flag / path /
        metacharacter raises :class:`ValueError` and never reaches the subprocess. The
        CLI's Rich panel + ASCII tree (197 lines for ``memory``) are condensed by the
        pure :func:`digest_impact` into a chat-sized answer; an unknown ref (whose error
        goes to stderr) yields an empty string rather than a guess.
        """
        return await self._run(
            "beadloom", "why", validate_graph_ref(ref), condense=digest_impact
        )

    async def project_health(
        self, check: str, *, since: str | None = None
    ) -> ProjectHealth:
        """Return the CONDENSED read-only beadloom report ``check`` (BOB-091.2).

        The DECISION — which report was asked for and its exact argv — belongs to the pure
        :func:`plan_health_form`; this method only executes it and condenses the output
        through :func:`digest_health`. An unrecognised check or a hostile ``since`` raises
        :class:`ValueError` before any exec (the same CLI holds the write subcommands).

        🔴 A non-zero exit status is NOT an error here, and that is structural rather than
        conditional: the runner returns stdout and never inspects ``returncode``, so
        ``lint``'s exit 1 (a violation), ``sync-check``'s exit 2 (a stale pair) and
        ``diff``'s exit 1 (a change) all arrive as what they are — verdicts. Bob answers
        "доки отстали", never "не смог посмотреть".
        """
        form = plan_health_form(check, since=since)
        report = await self._run(
            "beadloom",
            form.subcommand,
            *form.args,
            condense=partial(digest_health, form.check),
        )
        return ProjectHealth(check=form.check, report=report)

    async def list_tasks(self, query: str) -> str:
        """Execute the read-only ``bd`` form the pure planner picked for ``query``.

        The DECISION (ready queue / listing by status / one task / title search) is
        :func:`plan_tracker_query`; this method only runs it and applies the two
        honest degradations: an id ``bd show`` cannot resolve retries as a search,
        and a search that matches nothing degrades to the plain listing rather than
        to silence.
        """
        plan = plan_tracker_query(query)
        argument = plan.argument
        if plan.kind == "ready":
            return await self._run("bd", "ready")
        if plan.kind == "show" and argument is not None:
            return await self._show_or_search(argument)
        if plan.kind == "search" and argument is not None:
            return await self._search_or_list(argument)
        if plan.kind == "list" and argument is not None:
            return await self._run("bd", "list", "--status", argument)
        return await self._run("bd", "list")

    async def code_history(self, path: str) -> str:
        """Return the read-only git history linking ``path`` to its decisions (BOB-038).

        A bead/node key (``BOB-031`` / ``bob-4be.1``) routes to the commits that
        MENTION it (``git log --grep=<key> --oneline``); a repo-relative source path
        routes to the bounded history of that path
        (``git log --oneline -n <N> -- <path>``). The argv is built from the fixed
        forms only; an unsafe value (a flag, an absolute path, ``..`` traversal, or a
        non-key non-path token) is refused with :class:`DisallowedCommandError`
        without running git.
        """
        token = path.strip()
        if _is_bead_key(token):
            return await self._run("git", "log", f"--grep={token}", "--oneline")
        if not _is_safe_git_path(token):
            raise DisallowedCommandError(
                f"git history path {path!r} is not a safe repo-relative pathspec"
            )
        count = str(self._history_max_commits)
        return await self._run("git", "log", "--oneline", "-n", count, "--", token)

    async def recent_commits(self, count: int) -> str:
        """Return the last ``count`` commits repo-wide (``git log --oneline -n <N>``).

        ``count`` is clamped into ``[1, 50]`` by :func:`clamp_commit_count` before it
        reaches git, so the history is always bounded. No path, no ``--grep`` — a
        plain recent-commits view; the argv is the fixed repo-wide ``log`` form and
        the output is sanitised/truncated by :meth:`_run`.
        """
        bounded = str(clamp_commit_count(count))
        return await self._run("git", "log", "--oneline", "-n", bounded)

    async def task_comments(self, bead_id: str) -> str:
        """Return the tracker comments/checkpoints for ``bead_id`` (``bd comments``).

        ``bead_id`` is passed through :func:`validate_bead_id` first, so a flag or an
        injection-shaped value raises :class:`ValueError` and never reaches the
        subprocess. Read-only: ``bd comments`` lists a task's history, never writes.
        """
        return await self._run("bd", "comments", validate_bead_id(bead_id))

    async def show_task(self, bead_id: str) -> str:
        """Return the details of ``bead_id`` (``bd show <id>``, read-only).

        ``bead_id`` is validated by :func:`validate_bead_id` before exec (an id-shaped
        token only), so a flag/injection value is refused with :class:`ValueError`.
        🔴 When ``bd show`` finds nothing the key is retried as a title SEARCH: an
        epic key like ``BOB-087`` is NOT a bd identifier (that is ``bob-abk``) — it
        lives in the title — so answering "не существует" there was a tool defect,
        not a fact about the tracker.
        """
        return await self._show_or_search(validate_bead_id(bead_id))

    async def tasks_by_status(self, status: str | None) -> str:
        """List tracker tasks, optionally filtered by ``status`` (``bd list``).

        ``status`` is mapped to the stored-status enum by :func:`normalize_status`
        (English enum or a Russian synonym); an unknown or ``None`` status yields the
        unfiltered ``bd list`` (never a guessed filter). The resulting ``--status``
        value is always an allowlisted enum, so the read-only form invariant holds.
        """
        normalized = normalize_status(status)
        if normalized is None:
            return await self._run("bd", "list")
        return await self._run("bd", "list", "--status", normalized)

    async def read_file(self, path: str, *, max_lines: int) -> str:
        """Return up to ``max_lines`` of ``path`` — guard-checked BEFORE opening.

        The privacy guard is consulted first: a denied path raises
        :class:`DeniedPathError` with NO disk access. An allowed-but-missing file
        yields an honest "not found" message. Returned content is line-capped and
        run through the sanitiser.
        """
        candidate = Path(path)
        if not self._guard.allows_path(candidate):
            raise DeniedPathError(f"reading {path!r} is denied by the privacy guard")

        target = candidate if candidate.is_absolute() else self._guard.repo_root / path
        # Defence in depth at the filesystem boundary: the pure name-based guard above
        # cannot see where a SYMLINK actually points, so a link planted under an allowed
        # root (e.g. src/leak.md -> data/soul/SOUL.md) would otherwise leak denied
        # content. Resolve symlinks now and re-assert the REAL path stays inside an
        # allowed read-only root before opening — a link escaping into a denied root is
        # refused with no read. Containment is computed on realpaths consistently so a
        # symlinked repo root (e.g. /var -> /private/var on macOS) is not a false denial.
        if not self._real_path_is_allowed(target):
            raise DeniedPathError(
                f"reading {path!r} is denied by the privacy guard (resolves outside the "
                "read-only roots)"
            )
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return f"File not found: {path}"
        except OSError as exc:
            return f"Could not read {path}: {exc}"

        capped = "\n".join(raw.splitlines()[:max_lines])
        return self._guard.sanitize(self._truncate(capped))

    async def list_dir(self, path: str) -> str:
        """Return the entries of directory ``path`` — guard-checked, NON-recursive.

        The privacy guard is consulted first: a path escaping the repo raises
        :class:`DeniedPathError` with NO disk access. A missing path or a non-directory
        yields an honest message (never a fabricated listing). Otherwise each immediate
        child is rendered as ``name<TAB>kind[<TAB>size]``, sorted by name for
        determinism, then run through the sanitiser and char cap.
        """
        candidate = Path(path)
        if not self._guard.allows_path(candidate):
            raise DeniedPathError(f"listing {path!r} is denied by the privacy guard")
        target = candidate if candidate.is_absolute() else self._guard.repo_root / path
        if not self._real_path_is_allowed(target):
            raise DeniedPathError(
                f"listing {path!r} is denied by the privacy guard (resolves outside "
                "the repo)"
            )
        try:
            with os.scandir(target) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except (FileNotFoundError, NotADirectoryError):
            return f"Not a directory: {path}"
        except OSError as exc:
            return f"Could not list {path}: {exc}"

        if not entries:
            return f"Directory is empty: {path}"
        listing = "\n".join(_format_dir_entry(entry) for entry in entries)
        return self._guard.sanitize(self._truncate(listing))

    async def find_file(self, pattern: str) -> str:
        """Return repo-relative paths matching glob ``pattern`` across the repo tree.

        Walks the repo tree from the root (``rglob``), keeping paths whose name/glob
        matches ``pattern``. ``.git/`` and any entry whose real path escapes the repo
        (an outward symlink) are skipped; matches are sorted and capped at
        :data:`_FIND_FILE_MAX_RESULTS` with an honest truncation note. An empty result
        is reported honestly. Output is sanitised and char-capped.
        """
        token = pattern.strip()
        if not token:
            return "No files matching an empty pattern."
        repo_root = self._guard.repo_root
        matches = sorted(str(rel) for rel in self._iter_find_matches(repo_root, token))
        if not matches:
            return f"No files matching {pattern!r} found in the repo."
        truncated = len(matches) > _FIND_FILE_MAX_RESULTS
        shown = matches[:_FIND_FILE_MAX_RESULTS]
        body = "\n".join(shown)
        if truncated:
            body += (
                f"\n…[truncated: showing {_FIND_FILE_MAX_RESULTS} of "
                f"{len(matches)} matches]"
            )
        return self._guard.sanitize(self._truncate(body))

    def _iter_find_matches(self, repo_root: Path, pattern: str) -> Iterator[Path]:
        """Yield repo-relative match paths for ``pattern``, skipping ``.git`` + escapes.

        A defensive wrapper over ``rglob``: filesystem errors mid-walk, or an
        absolute / unsupported glob (``rglob`` raises :class:`NotImplementedError`
        for a non-relative pattern, :class:`ValueError` for an empty one), stop
        iteration and yield NOTHING — an honest-empty result (INV-N5), like a
        non-existent file, never an opaque tool-failure. ``.git`` entries and outward
        symlinks are dropped.
        """
        try:
            candidates = list(repo_root.rglob(pattern))
        except (OSError, NotImplementedError, ValueError):
            return
        for candidate in candidates:
            try:
                rel = candidate.relative_to(repo_root)
            except ValueError:
                continue
            if _GIT_DIR in rel.parts:
                continue
            # 🔴 bob-zmp: the guard is asked here too, not only in read_file/list_dir —
            # otherwise the refusal to LIST a secret store is one glob away from being
            # bypassed (``find_file('.secrets/*')`` would enumerate the keys the guard
            # just refused to show). Containment alone (below) cannot see key shapes.
            if not self._guard.allows_path(candidate):
                continue
            if not self._real_path_is_allowed(candidate):
                continue
            yield rel

    def _real_path_is_allowed(self, target: Path) -> bool:
        """Whether ``target``'s symlink-resolved real path stays inside the repo.

        Computes containment on realpaths consistently (both the candidate and the
        repo-root anchor are run through :func:`os.path.realpath`) so a symlinked repo
        root is not a false denial, while a symlink that escapes the repo entirely (an
        absolute system path) is caught here — the defence the pure name-based guard
        structurally cannot provide. Under the BOB-067 full-repo invariant the anchor
        is the repo root itself (:data:`ALLOWED_ROOTS` = ``(".",)``).
        """
        real_target = Path(os.path.realpath(target))
        repo_root = self._guard.repo_root
        for root in ALLOWED_ROOTS:
            real_root = Path(os.path.realpath(repo_root / root))
            if real_target == real_root or real_root in real_target.parents:
                return True
        return False

    # --- internals ------------------------------------------------------------

    async def _show_or_search(self, ident: str) -> str:
        """``bd show <ident>``, retried as a title search when it resolves nothing.

        Symmetric with the ``ctx``→``search`` fallback on the architecture side: an
        id-shaped token that the tracker cannot resolve is still probably a REAL key
        (an epic key lives in titles), so the question is answered instead of denied.
        """
        detail = await self._run("bd", "show", ident)
        if detail.strip():
            return detail
        return await self._search_tracker(ident)

    async def _search_or_list(self, term: str) -> str:
        """Search the tracker for ``term``, degrading to the plain listing if empty."""
        found = await self._search_tracker(term)
        if found.strip():
            return found
        return await self._run("bd", "list")

    async def _search_tracker(self, term: str) -> str:
        """Run the fixed ``bd search <term> --status all`` form and digest the result.

        ``--status all`` is part of the FORM, not a choice: without it a finished epic
        is invisible. The output is condensed by the pure digest so a key matching
        dozens of tasks answers with the epic + what is alive + the counts, never a
        forty-line dump (BOB-086).
        """
        raw = await self._run("bd", "search", term, *_BD_SEARCH_TAIL_FORM)
        return digest_search_results(raw)

    async def _run(
        self,
        binary: str,
        subcommand: str,
        *args: str,
        condense: Callable[[str], str] | None = None,
    ) -> str:
        """Validate against the allowlist, then exec ``binary subcommand args``.

        Refuses (without executing) any unknown binary, off-allowlist subcommand, or
        flag-looking argument. On success the stdout is denoised, optionally CONDENSED,
        then truncated + sanitised.

        🔴 ``condense`` runs BEFORE the char cap, and that order is the point (BOB-091.2,
        found by running the live CLI through this path). ``beadloom sync-check`` prints
        48 KB in this repo while the cap is 20 000 chars, so a digest applied AFTER the
        cap counted only the pairs that FITTED and answered "274 пары" for 585 — a wrong
        number stated confidently, which is worse than a dump. Condensing first also makes
        the cap what it should be: a last-resort bound on an already-short answer.
        """
        entry = self._allow.get(binary)
        if entry is None:
            raise DisallowedCommandError(f"binary {binary!r} is not allowed")
        bin_path, allowed_subs = entry
        if subcommand not in allowed_subs:
            raise DisallowedCommandError(
                f"{binary} {subcommand!r} is not a read-only allowlisted subcommand"
            )
        self._validate_args(binary, subcommand, args)

        argv = [bin_path, subcommand, *args]
        stdout = await self._runner(argv, timeout=self._timeout)
        text = _strip_noise_tail(stdout)
        if condense is not None:
            text = condense(text)
        return self._guard.sanitize(self._truncate(text))

    def _validate_args(
        self, binary: str, subcommand: str, args: tuple[str, ...]
    ) -> None:
        """Refuse any arg outside the read-only allowlist (no arbitrary args/flags).

        The per-binary form gates live in their own methods (:meth:`_validate_git_args`,
        :meth:`_validate_beadloom_args`); what remains HERE is the routing plus the
        default rule that closes everything else: no flag-looking argument is forwarded.
        The controlled flag-bearing exceptions are the ``bd list --status <enum>`` form
        (the literal ``--status`` flag paired with one stored-status enum value from a
        FIXED allowlist) and the ``bd search <term> --status all`` form (fixed tail,
        sanitiser-validated term). Every other flag-looking arg — a status outside the
        enum, an extra git flag, an out-of-form git shape, another beadloom flag such as
        ``--project`` or ``--json`` — is refused before exec.
        """
        if binary == "git":
            self._validate_git_args(subcommand, args)
            return
        if binary == "beadloom":
            self._validate_beadloom_args(subcommand, args)
            return
        if binary == "bd" and subcommand == "search":
            if _is_allowed_bd_search_form(args):
                return
            raise DisallowedCommandError(
                f"bd search arguments {args!r} are not an allowlisted read-only form"
            )
        if binary == "bd" and subcommand == "list" and args:
            if args in _BD_LIST_ARG_FORMS:
                return
            raise DisallowedCommandError(
                f"bd list arguments {args!r} are not an allowlisted read-only form"
            )
        self._refuse_flag_like(args)

    def _validate_beadloom_args(self, subcommand: str, args: tuple[str, ...]) -> None:
        """Refuse any beadloom invocation outside the fixed read-only forms.

        Three families, each an exact-shape gate: the ``graph`` forms (overview /
        ``<ref> [--depth <N>]`` / the C4 ``--scope`` view), ``why <ref>`` (exactly one
        validated ref), and the health reports (``status`` / ``prime`` / ``doctor`` /
        ``sync-check`` take NO argument, ``lint`` takes exactly ``--no-reindex --strict``,
        ``diff`` exactly ``--since <git-ref>``). The remaining read subcommands (``ctx`` /
        ``search``) take a plain value, so they fall back to the default rule — no
        flag-looking argument at all.
        """
        if subcommand == "graph":
            if _is_allowed_graph_form(args):
                return
            raise DisallowedCommandError(
                f"beadloom graph arguments {args!r} are not an allowlisted read-only form"
            )
        if subcommand == "why":
            if _is_allowed_why_form(args):
                return
            raise DisallowedCommandError(
                f"beadloom why arguments {args!r} are not an allowlisted read-only form"
            )
        if subcommand in _HEALTH_SUBCOMMANDS:
            if _is_allowed_health_form(subcommand, args):
                return
            raise DisallowedCommandError(
                f"beadloom {subcommand} arguments {args!r} are not an allowlisted "
                "read-only form"
            )
        self._refuse_flag_like(args)

    def _refuse_flag_like(self, args: tuple[str, ...]) -> None:
        """The default rule: no flag-looking argument is ever forwarded."""
        for arg in args:
            if _looks_like_flag(arg):
                raise DisallowedCommandError(
                    f"flag-like argument {arg!r} is not permitted"
                )

    def _validate_git_args(self, subcommand: str, args: tuple[str, ...]) -> None:
        """Refuse any git invocation outside the fixed read-only ``log`` forms.

        Only ``git log`` with an exact allowlisted shape — ``--grep=<bead-key>
        --oneline``, the repo-wide ``--oneline -n <N>``, or
        ``--oneline [-n <N>] -- <path>`` — passes; every other subcommand or arg
        shape (an extra flag, a path-injection, a non-key grep value) is refused
        before execution.
        """
        if subcommand != "log":
            raise DisallowedCommandError(
                f"git {subcommand!r} is not a read-only allowlisted subcommand"
            )
        if (
            _is_allowed_git_grep_form(args)
            or _is_allowed_git_repo_wide_form(args)
            or _is_allowed_git_path_form(args)
        ):
            return
        raise DisallowedCommandError(
            f"git log arguments {args!r} are not an allowlisted read-only form"
        )

    def _truncate(self, text: str) -> str:
        """Cap ``text`` at the configured char limit with a short marker."""
        if len(text) <= self._max_output_chars:
            return text
        return text[: self._max_output_chars] + _TRUNCATION_MARKER


class _ExecRunner:
    """Default runner: ``create_subprocess_exec`` with a hard timeout, no shell."""

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await _drain(proc)
            return f"(introspection command timed out after {timeout:g}s)"
        return out.decode("utf-8", errors="replace")


async def _drain(proc: asyncio.subprocess.Process) -> None:
    """Reap a killed subprocess so no zombie/transport warning is left behind."""
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()
