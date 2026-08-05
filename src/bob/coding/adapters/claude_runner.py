# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""SubprocessClaudeRunner — run the local ``claude`` CLI and stream its events.

The infrastructure adapter realising :class:`bob.coding.ports.ClaudeCodeRunner`
(BOB-039 .2). It runs ``claude`` headless via ``asyncio.create_subprocess_exec``
(NEVER a shell — the prompt is a single discrete argv item, never interpolated):

    claude -p <prompt> --output-format stream-json --verbose --permission-mode <mode>

``mode`` is validated against the allowlist policy of the pure domain core
(:mod:`bob.coding.sandbox_policy`): ``plan`` — a plan with NO edits, the plan gate;
``acceptEdits`` — apply changes inside the worktree; and ONLY under the explicit owner
flag ``allow_bypass`` (config ``coder.allow_bypass``, default OFF) also
``bypassPermissions``. Any other mode is refused before the process starts. The same
core sanitises the optional ``extra_dirs`` (config ``coder.extra_dirs``, default empty)
into the ``--add-dir`` argv fragment appended AFTER the fixed head — both relaxations
are inert by default, so the shipped argv is unchanged. Stdout is read as NDJSON
line-by-line: each line is
parsed by the shared :func:`bob.coding.stream_json.parse_event` and the parsed object
yielded as one event (an async generator).
Partial / garbage / non-object lines are skipped (never crash); a per-stream timeout,
a max-event count and a max-byte budget bound the run; and the underlying process is
killed + reaped on a timeout or an early break (no zombies).

The streaming subprocess boundary is injected (``runner``) so tests drive the argv /
NDJSON parse / cleanup with a fake and never spawn the real ``claude``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from bob.coding.push_guard import guarded_spawn_env
from bob.coding.sandbox_policy import (
    ClaudeRunError,
    extra_dir_argv,
    is_allowed_mode,
)
from bob.coding.stream_json import STREAM_LIMIT, parse_event

if TYPE_CHECKING:
    from bob.identity.spawn_isolation import SpawnIsolation

__all__ = ["ClaudeRunError", "SubprocessClaudeRunner"]

logger = logging.getLogger(__name__)

# Default resource bounds (overridable via the constructor): a generous wall-clock
# ceiling for a real coding run, a hard cap on the number of events, and a byte budget
# on total stdout so a runaway stream cannot exhaust memory.
_DEFAULT_TIMEOUT_S = 600.0
_DEFAULT_MAX_EVENTS = 10_000
_DEFAULT_MAX_BYTES = 10_000_000


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
        allow_bypass: bool = False,
        extra_dirs: Sequence[str] = (),
        isolation: SpawnIsolation | None = None,
    ) -> None:
        # 🔴 Push guard (BOB-087.E): when the owner relaxes the sandbox the DEFAULT
        # spawner carries a git config in its environment that makes every network push
        # from the tree die on a non-existent remote helper. Only the default (real
        # process) boundary is guarded — an injected fake spawns nothing.
        # 🔴 Credential isolation (BOB-089.C): under ``coder.isolated_clone`` the same
        # spawn ALSO stops seeing the owner's credential helper (substituted global git
        # config, disabled system config, reset helper list, no ambient gh token / ssh
        # agent) — see :mod:`bob.identity.spawn_isolation`. ``None`` → unchanged spawn.
        self._runner: StreamLineRunner = runner or _ExecStreamRunner(
            guard_push=allow_bypass, isolation=isolation
        )
        self._claude_bin = claude_bin
        self._timeout = timeout
        self._max_events = max_events
        self._max_bytes = max_bytes
        # Owner-only sandbox relaxations (BOB-087.D2), both inert by default: the bypass
        # mode stays outside the allowlist and the (sanitised once, here) --add-dir
        # fragment is empty, so the argv below is byte-identical to the shipped form.
        self._allow_bypass = allow_bypass
        self._extra_dir_argv = extra_dir_argv(extra_dirs)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        """Run ``claude`` in ``workdir`` under ``mode``; yield stream-json events."""
        if not is_allowed_mode(mode, allow_bypass=self._allow_bypass):
            raise ClaudeRunError(
                f"mode {mode!r} is not an allowlisted --permission-mode"
            )
        # Argv order (fixed): the binary, the prompt, the stream-json/verbose head, the
        # ``--permission-mode <mode>`` pair, and LAST the optional ``--add-dir`` pairs —
        # so an empty relaxation leaves the pre-D2 argv untouched.
        argv = [
            self._claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            mode,
            *self._extra_dir_argv,
        ]
        stream = self._runner(argv, cwd=workdir, timeout=self._timeout)
        events = 0
        total_bytes = 0
        try:
            async for line in stream:
                total_bytes += len(line)
                if total_bytes > self._max_bytes or events >= self._max_events:
                    break
                event = parse_event(line)
                if event is None:
                    continue
                yield event
                events += 1
        finally:
            # Closing the generator runs its ``finally`` — killing + reaping the real
            # process — so an early break (bound hit / caller stops) leaves no zombie.
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()


class _ExecStreamRunner:
    """Default runner: ``create_subprocess_exec``, read stdout line-by-line, no shell."""

    def __init__(
        self, *, guard_push: bool = False, isolation: SpawnIsolation | None = None
    ) -> None:
        # ``None`` (the default) means «spawn without ``env=``» — the inherited
        # environment, byte-identical to the pre-guard spawn. Under ``guard_push`` it is
        # the inherited environment PLUS the push-blocking git config, and under
        # ``isolation`` MINUS the owner's credentials (see :mod:`bob.coding.push_guard`,
        # incl. what those measures honestly do NOT cover).
        self._env = guarded_spawn_env(os.environ, active=guard_push, isolation=isolation)

    async def __call__(
        self, argv: list[str], *, cwd: str, timeout: float
    ) -> AsyncIterator[str]:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=STREAM_LIMIT,
            env=self._env,
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
                except ValueError:
                    # A single line exceeded ``STREAM_LIMIT`` (LimitOverrunError ->
                    # ValueError). The buffer cannot advance past it without re-raising
                    # forever, so end the stream gracefully (treat as EOF) rather than
                    # crash the pump — do NOT ``continue``.
                    logger.warning(
                        "claude stdout line exceeded the %d-byte stream limit; "
                        "ending read",
                        STREAM_LIMIT,
                    )
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
