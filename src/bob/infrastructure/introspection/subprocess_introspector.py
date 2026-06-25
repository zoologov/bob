# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SubprocessRepoIntrospector — read-only self-introspection over the local repo.

Realises :class:`bob.domain.ports.RepoIntrospector` (BOB-017 Phase A). Two seams:

* **CLI introspection** — ``beadloom`` (``ctx`` / ``graph`` / ``why`` / ``search``)
  and ``bd`` (``ready`` / ``show`` / ``list``) run via
  ``asyncio.create_subprocess_exec`` (NEVER a shell, so no metacharacter injection)
  against a FIXED allowlist of read-only subcommands. Anything off the allowlist — a
  write subcommand, an unknown binary, a flag-looking argument that could smuggle
  behaviour — is refused with :class:`DisallowedCommandError` and never executed. The
  sole flag-bearing exception is the controlled ``bd list --status <enum>`` form
  (``--status`` paired with one stored-status enum value from a fixed set); a status
  outside the enum, or any other flag, is still refused. Free-text questions ground
  via ``beadloom search`` (``ctx`` needs an exact ref, with a ``ctx``→``search``
  fallback on empty); trailing tooling-noise lines (status legend / Tip / ``--limit``
  hint) are stripped. Output is bounded by a char cap and run through the privacy
  sanitiser; each run has a hard timeout.
* **File reads** — :meth:`read_file` consults the pure
  :class:`~bob.domain.introspection.privacy_guard.PrivacyGuard` BEFORE opening any
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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bob.domain.introspection.privacy_guard import ALLOWED_ROOTS

if TYPE_CHECKING:
    from bob.domain.introspection.privacy_guard import PrivacyGuard

# Fixed allowlist of read-only subcommands, keyed by binary. NOTHING else runs.
_BEADLOOM_SUBCOMMANDS: frozenset[str] = frozenset({"ctx", "graph", "why", "search"})
_BD_SUBCOMMANDS: frozenset[str] = frozenset({"ready", "show", "list"})
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

# Exact argv lengths of the three permitted ``git log`` forms (after the subcommand):
# ``--grep=<key> --oneline`` (2), ``--oneline -- <path>`` (3), and the bounded
# ``--oneline -n <N> -- <path>`` (5). Named so the shape checks carry no magic value.
_GIT_GREP_FORM_LEN = 2
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


# Intent keywords (RU + EN) mapping a free-text tracker query to a ``bd list`` form.
# Order matters: the FIRST matching status wins, with "all" as the unfiltered list.
_READY_KEYWORDS: tuple[str, ...] = ("ready", "готов")
_CLOSED_KEYWORDS: tuple[str, ...] = (
    "закрыт", "недавн", "истори", "recent", "closed", "history",
)
_IN_PROGRESS_RE = re.compile(r"в работе|in[\s-]?progress")
_ALL_KEYWORDS: tuple[str, ...] = ("все", "весь", "all", "list", "список")


def _wants_ready(token: str) -> bool:
    """Whether a free-text tracker query asks for the ready queue."""
    low = token.lower()
    return any(kw in low for kw in _READY_KEYWORDS)


def _list_status_for(token: str) -> str | None:
    """Map a listing query to a ``bd list`` status enum (``None`` for an "all" listing).

    Only call when :func:`_is_listing_query` is true. Returns ``closed`` /
    ``in_progress`` for a filtered listing, ``None`` for an explicit unfiltered list.
    """
    low = token.lower()
    if any(kw in low for kw in _CLOSED_KEYWORDS):
        return "closed"
    if _IN_PROGRESS_RE.search(low):
        return "in_progress"
    return None


def _is_listing_query(token: str) -> bool:
    """Whether a free-text tracker query asks for a listing (vs. a single id)."""
    low = token.lower()
    if _IN_PROGRESS_RE.search(low):
        return True
    return any(
        kw in low for kw in (*_CLOSED_KEYWORDS, *_ALL_KEYWORDS)
    )


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

    async def list_tasks(self, query: str) -> str:
        """Route a tracker query to the right read-only ``bd`` form.

        A task id → ``bd show <id>``; a request for closed/recent/history,
        in-progress, or all tasks → the matching ``bd list [--status <enum>]``; an
        empty or "ready" query → ``bd ready``.
        """
        token = query.strip()
        if not token or _wants_ready(token):
            return await self._run("bd", "ready")
        if _is_listing_query(token):
            status = _list_status_for(token)
            if status is None:
                return await self._run("bd", "list")
            return await self._run("bd", "list", "--status", status)
        if _is_ref_id(token):
            return await self._run("bd", "show", token)
        # No id, no listing keyword: fall back to the unfiltered list rather than a
        # doomed ``bd show`` on free text.
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

    def _real_path_is_allowed(self, target: Path) -> bool:
        """Whether ``target``'s symlink-resolved real path stays inside an allowed root.

        Computes containment on realpaths consistently (both the candidate and the
        allowed roots are run through :func:`os.path.realpath`) so a symlinked repo
        root is not a false denial, while a symlink that escapes an allowed root into a
        denied tree (SOUL / ``bob.db`` / ``.env`` / ``config``) is caught here — the
        defence the pure name-based guard structurally cannot provide.
        """
        real_target = Path(os.path.realpath(target))
        repo_root = self._guard.repo_root
        for root in ALLOWED_ROOTS:
            real_root = Path(os.path.realpath(repo_root / root))
            if real_target == real_root or real_root in real_target.parents:
                return True
        return False

    # --- internals ------------------------------------------------------------

    async def _run(self, binary: str, subcommand: str, *args: str) -> str:
        """Validate against the allowlist, then exec ``binary subcommand args``.

        Refuses (without executing) any unknown binary, off-allowlist subcommand, or
        flag-looking argument. On success the stdout is truncated + sanitised.
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
        return self._guard.sanitize(self._truncate(_strip_noise_tail(stdout)))

    def _validate_args(
        self, binary: str, subcommand: str, args: tuple[str, ...]
    ) -> None:
        """Refuse any arg outside the read-only allowlist (no arbitrary args/flags).

        Two controlled flag-bearing exceptions exist: the ``bd list --status <enum>``
        form (the literal ``--status`` flag paired with one stored-status enum value
        from a FIXED allowlist), and the ``git log`` fixed forms (a bounded
        ``--oneline -n <N> -- <path>`` or ``--grep=<bead-key> --oneline``, each
        dynamic slot validated). Every other flag-looking arg — a status outside the
        enum, an extra git flag, an out-of-form git shape — is refused before exec.
        """
        if binary == "git":
            self._validate_git_args(subcommand, args)
            return
        if binary == "bd" and subcommand == "list" and args:
            if args in _BD_LIST_ARG_FORMS:
                return
            raise DisallowedCommandError(
                f"bd list arguments {args!r} are not an allowlisted read-only form"
            )
        for arg in args:
            if _looks_like_flag(arg):
                raise DisallowedCommandError(
                    f"flag-like argument {arg!r} is not permitted"
                )

    def _validate_git_args(self, subcommand: str, args: tuple[str, ...]) -> None:
        """Refuse any git invocation outside the fixed read-only ``log`` forms.

        Only ``git log`` with an exact allowlisted shape — ``--grep=<bead-key>
        --oneline`` or ``--oneline [-n <N>] -- <path>`` — passes; every other
        subcommand or arg shape (an extra flag, a path-injection, a non-key grep
        value) is refused before execution.
        """
        if subcommand != "log":
            raise DisallowedCommandError(
                f"git {subcommand!r} is not a read-only allowlisted subcommand"
            )
        if _is_allowed_git_grep_form(args) or _is_allowed_git_path_form(args):
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
