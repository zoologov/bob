# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Shell-free command boundary shared by the git + gh coding adapters (BOB-039 .2).

A tiny injectable seam: :class:`CommandRunner` runs a FIXED argv list and returns its
stdout. The default :class:`ExecRunner` uses ``asyncio.create_subprocess_exec`` (NEVER
a shell — no metacharacter injection), enforces a hard timeout (killing + reaping a
stuck process so no zombie is left behind), and raises :class:`CommandError` on a
non-zero exit or a timeout. The argv is always built from validated, fixed forms by
the calling adapter — this module never interpolates anything into a shell.

The streaming ``claude`` runner has a different shape (an NDJSON line iterator) and
lives with its adapter; this seam is the one-shot "run argv, capture stdout" case the
``git worktree`` and ``gh pr create`` adapters share.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Protocol

__all__ = ["CommandError", "CommandRunner", "ExecRunner"]

# Default per-command wall-clock ceiling (seconds): generous for a git/gh call, low
# enough that a stuck process cannot wedge a session. Config-tunable per adapter.
_DEFAULT_TIMEOUT_S = 60.0


class CommandError(Exception):
    """A shell-free subprocess invocation failed (non-zero exit or timeout)."""


class CommandRunner(Protocol):
    """The injected subprocess boundary: run ``argv`` with a timeout, return stdout."""

    async def __call__(self, argv: list[str], *, timeout: float) -> str: ...


class ExecRunner:
    """Default runner: ``create_subprocess_exec`` capturing stdout, no shell."""

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as exc:
            proc.kill()
            await _drain(proc)
            raise CommandError(
                f"command {argv[0]!r} timed out after {timeout:g}s"
            ) from exc
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            raise CommandError(
                f"command {argv[0]!r} exited with code {proc.returncode}: {detail}"
            )
        return out.decode("utf-8", errors="replace")


async def _drain(proc: asyncio.subprocess.Process) -> None:
    """Reap a killed subprocess so no zombie/transport warning is left behind."""
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()


DEFAULT_TIMEOUT_S = _DEFAULT_TIMEOUT_S
