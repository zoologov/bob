# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SubprocessRepoIntrospector — read-only self-introspection over the local repo.

Realises :class:`bob.domain.ports.RepoIntrospector` (BOB-017 Phase A). Two seams:

* **CLI introspection** — ``beadloom`` (``ctx`` / ``graph`` / ``why`` / ``search``)
  and ``bd`` (``ready`` / ``show``) run via ``asyncio.create_subprocess_exec``
  (NEVER a shell, so no metacharacter injection) against a FIXED allowlist of
  read-only subcommands. Anything off the allowlist — a write subcommand, an
  unknown binary, a flag-looking argument that could smuggle behaviour — is refused
  with :class:`DisallowedCommandError` and never executed. Output is bounded by a
  char cap and run through the privacy sanitiser; each run has a hard timeout.
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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bob.domain.introspection.privacy_guard import ALLOWED_ROOTS

if TYPE_CHECKING:
    from bob.domain.introspection.privacy_guard import PrivacyGuard

# Fixed allowlist of read-only subcommands, keyed by binary. NOTHING else runs.
_BEADLOOM_SUBCOMMANDS: frozenset[str] = frozenset({"ctx", "graph", "why", "search"})
_BD_SUBCOMMANDS: frozenset[str] = frozenset({"ready", "show"})

# Default resource bounds (overridable via the constructor).
_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_MAX_OUTPUT_CHARS = 20_000

_TRUNCATION_MARKER = "\n…[truncated]"


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
    ) -> None:
        self._guard = guard
        self._runner: _CommandRunner = runner or _ExecRunner()
        self._timeout = timeout
        self._max_output_chars = max_output_chars
        self._beadloom_bin = beadloom_bin
        self._bd_bin = bd_bin
        # Map the canonical binary name -> (configured path, allowed subcommands).
        self._allow: dict[str, tuple[str, frozenset[str]]] = {
            "beadloom": (beadloom_bin, _BEADLOOM_SUBCOMMANDS),
            "bd": (bd_bin, _BD_SUBCOMMANDS),
        }

    # --- RepoIntrospector port ------------------------------------------------

    async def architecture_context(self, ref: str) -> str:
        """Run ``beadloom ctx <ref>`` (read-only graph/architecture context)."""
        return await self._run("beadloom", "ctx", ref)

    async def search_code(self, query: str) -> str:
        """Run ``beadloom search <query>`` (read-only FTS over nodes/docs)."""
        return await self._run("beadloom", "search", query)

    async def list_tasks(self, query: str) -> str:
        """Run ``bd show <query>`` for a specific task, else ``bd ready`` (read-only)."""
        if query.strip():
            return await self._run("bd", "show", query)
        return await self._run("bd", "ready")

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
        for arg in args:
            if _looks_like_flag(arg):
                raise DisallowedCommandError(
                    f"flag-like argument {arg!r} is not permitted"
                )

        argv = [bin_path, subcommand, *args]
        stdout = await self._runner(argv, timeout=self._timeout)
        return self._guard.sanitize(self._truncate(stdout))

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
