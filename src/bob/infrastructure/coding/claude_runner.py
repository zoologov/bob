# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SubprocessClaudeRunner — run the local ``claude`` CLI and stream its events.

The infrastructure adapter realising :class:`bob.domain.ports.ClaudeCodeRunner`
(BOB-039 .2). It runs ``claude`` headless via ``asyncio.create_subprocess_exec``
(NEVER a shell — the prompt is a single discrete argv item, never interpolated):

    claude -p <prompt> --output-format stream-json --verbose --permission-mode <mode>

``mode`` is validated against a FIXED allowlist (``plan`` — a plan with NO edits, the
plan gate; ``acceptEdits`` — apply changes inside the worktree); any other mode is
refused before the process starts. Stdout is read as NDJSON line-by-line: each line is
``json.loads``-ed and the parsed object yielded as one event (an async generator).
Partial / garbage / non-object lines are skipped (never crash); a per-stream timeout,
a max-event count and a max-byte budget bound the run; and the underlying process is
killed + reaped on a timeout or an early break (no zombies).

The streaming subprocess boundary is injected (``runner``) so tests drive the argv /
NDJSON parse / cleanup with a fake and never spawn the real ``claude``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Protocol

__all__ = ["ClaudeRunError", "SubprocessClaudeRunner"]

# The FIXED permission-mode allowlist. ``plan`` produces a plan with no edits (the plan
# gate); ``acceptEdits`` applies changes inside the isolated worktree. Nothing else —
# in particular no ``bypassPermissions`` — is ever passed to ``claude``.
_ALLOWED_MODES: frozenset[str] = frozenset({"plan", "acceptEdits"})

# Default resource bounds (overridable via the constructor): a generous wall-clock
# ceiling for a real coding run, a hard cap on the number of events, and a byte budget
# on total stdout so a runaway stream cannot exhaust memory.
_DEFAULT_TIMEOUT_S = 600.0
_DEFAULT_MAX_EVENTS = 10_000
_DEFAULT_MAX_BYTES = 10_000_000


class ClaudeRunError(Exception):
    """A claude run was refused (mode outside the allowlist) before it started."""


class StreamLineRunner(Protocol):
    """Injected streaming boundary: run ``argv`` in ``cwd``, yield stdout lines.

    Realised by :class:`_ExecStreamRunner` (``create_subprocess_exec``, reading stdout
    line-by-line under a deadline); a fake substitutes in tests. The returned iterator
    is closed by the adapter on an early break so the process is killed + reaped.
    """

    def __call__(
        self, argv: list[str], *, cwd: str, timeout: float
    ) -> AsyncIterator[str]: ...


class SubprocessClaudeRunner:
    """Run ``claude`` headless and stream its ``--output-format stream-json`` events."""

    def __init__(
        self,
        *,
        runner: StreamLineRunner | None = None,
        claude_bin: str = "claude",
        timeout: float = _DEFAULT_TIMEOUT_S,
        max_events: int = _DEFAULT_MAX_EVENTS,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._runner: StreamLineRunner = runner or _ExecStreamRunner()
        self._claude_bin = claude_bin
        self._timeout = timeout
        self._max_events = max_events
        self._max_bytes = max_bytes

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        """Run ``claude`` in ``workdir`` under ``mode``; yield stream-json events."""
        if mode not in _ALLOWED_MODES:
            raise ClaudeRunError(
                f"mode {mode!r} is not an allowlisted --permission-mode"
            )
        argv = [
            self._claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            mode,
        ]
        stream = self._runner(argv, cwd=workdir, timeout=self._timeout)
        events = 0
        total_bytes = 0
        try:
            async for line in stream:
                total_bytes += len(line)
                if total_bytes > self._max_bytes or events >= self._max_events:
                    break
                event = _parse_event(line)
                if event is None:
                    continue
                yield event
                events += 1
        finally:
            # Closing the generator runs its ``finally`` — killing + reaping the real
            # process — so an early break (bound hit / caller stops) leaves no zombie.
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()


def _parse_event(line: str) -> Mapping[str, object] | None:
    """Parse one NDJSON line into an event mapping; tolerate blank/garbage lines."""
    text = line.strip()
    if not text:
        return None
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, Mapping):
        return decoded
    return None


class _ExecStreamRunner:
    """Default runner: ``create_subprocess_exec``, read stdout line-by-line, no shell."""

    async def __call__(
        self, argv: list[str], *, cwd: str, timeout: float
    ) -> AsyncIterator[str]:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        try:
            stdout = proc.stdout
            if stdout is None:
                return
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(stdout.readline(), timeout=remaining)
                except TimeoutError:
                    break
                if not raw:
                    break
                yield raw.decode("utf-8", errors="replace")
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await _drain(proc)


async def _drain(proc: asyncio.subprocess.Process) -> None:
    """Reap a killed/finished subprocess so no zombie/transport warning is left."""
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()
