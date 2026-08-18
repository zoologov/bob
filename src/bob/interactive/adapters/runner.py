# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=infrastructure

"""InteractiveClaudeRunner — a PERSISTENT bidirectional ``claude`` session (BOB-083 .2).

The infrastructure adapter realising :class:`bob.coding.ports.InteractiveRunner`. Unlike
the one-shot :class:`bob.coding.adapters.claude_runner.SubprocessClaudeRunner` (which runs
``claude -p <prompt>`` to EOF and throws its process away), this runner holds a LONG-LIVED
process with an OPEN stdin so the owner can steer ``claude`` in real time:

    claude -p --input-format stream-json --output-format stream-json --verbose
           --permission-mode <mode>

It is spawned via ``asyncio.create_subprocess_exec`` (NEVER a shell — each argv item is a
discrete token) with ``stdin=PIPE, stdout=PIPE, stderr=PIPE``, and the process handle is
RETAINED on the instance. :meth:`feed` encodes an owner text turn as ONE stream-json
``user`` line (:func:`encode_user_message`) and writes it to stdin; :meth:`events` reads
stdout NDJSON line-by-line (each ``json.loads``-ed, garbage skipped); :meth:`close`
terminates the process, kills it if it does not exit within a short grace, and reaps it —
idempotent, best-effort, never raising, so no zombie is left behind.

The spawn argv itself is NOT assembled here: it is the pure domain policy
:func:`bob.interactive.argv_policy.build_interactive_argv` (with
:func:`~bob.interactive.argv_policy.extract_session_id` reading the init frame's session id) —
this adapter only carries those verdicts to the process boundary.

``mode`` is validated against the SAME allowlist policy as the one-shot runner
(:mod:`bob.coding.sandbox_policy`), including the owner-only ``allow_bypass`` /
``extra_dirs`` relaxations (BOB-087.D2) — both OFF by default, so the spawn argv is
unchanged. The bidirectional subprocess boundary is injected (``spawner``) so tests drive
the argv / stdin / NDJSON / cleanup with a fake and never spawn the real ``claude``.

This is a pure transport adapter: NO session / state / worktree logic lives here (that is
the interactive-session manager, BOB-083 .3).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Protocol

from bob.coding.push_guard import guarded_spawn_env
from bob.coding.sandbox_policy import ClaudeRunError, is_allowed_mode
from bob.coding.stream_json import STREAM_LIMIT, parse_event
from bob.interactive.argv_policy import build_interactive_argv, extract_session_id
from bob.interactive.tool_permissions import tool_permission_argv

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence

    from bob.identity.spawn_isolation import SpawnIsolation

__all__ = [
    "InteractiveClaudeRunner",
    "InteractiveRunError",
    "encode_user_message",
]

logger = logging.getLogger(__name__)

# Grace (seconds) between ``terminate()`` (SIGTERM) and the ``kill()`` (SIGKILL) fallback
# on close: give ``claude`` a moment to exit cleanly before it is forced.
_DEFAULT_TERMINATE_GRACE_S = 5.0


class InteractiveRunError(Exception):
    """An interactive runner was misdriven (e.g. re-opened while already live)."""


def encode_user_message(text: str) -> str:
    """Encode ``text`` as ONE stream-json ``user`` input line for ``--input-format``.

    Pure and I/O-free (a mutation target). Produces the single-line JSON frame that
    ``claude --input-format stream-json`` reads from stdin — the Anthropic message
    envelope with a single text content block. ``json.dumps`` escapes the payload's own
    quotes / newlines / backslashes, so the frame is always exactly one NDJSON line.
    """
    frame = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }
    return json.dumps(frame, ensure_ascii=False)


class InteractiveProcess(Protocol):
    """A spawned bidirectional process: write to stdin, read stdout, stop.

    Realised by :class:`_ExecInteractiveProcess` (wrapping an
    ``asyncio.subprocess.Process``); a fake substitutes in tests. All methods are
    best-effort — a dead process must not raise.
    """

    async def feed(self, data: bytes) -> None:
        """Write raw ``data`` to stdin and flush (drain)."""
        ...

    def read_lines(self) -> AsyncIterator[str]:
        """Async-iterate decoded stdout lines until the process exits (EOF)."""
        ...

    def terminate(self) -> None:
        """Request a clean stop (SIGTERM); a no-op if already exited."""
        ...

    def kill(self) -> None:
        """Force stop (SIGKILL); a no-op if already exited."""
        ...

    async def wait(self, *, timeout: float | None = None) -> bool:
        """Reap the process; return ``True`` if it exited (within ``timeout``)."""
        ...

    @property
    def alive(self) -> bool:
        """Whether the process is still running."""
        ...


class InteractiveProcessSpawner(Protocol):
    """Injected boundary: spawn ``argv`` in ``cwd`` as an :class:`InteractiveProcess`."""

    def __call__(
        self, argv: list[str], *, cwd: str
    ) -> Awaitable[InteractiveProcess]: ...


class InteractiveClaudeRunner:
    """Hold a persistent ``claude`` process and drive it over stdin/stdout."""

    def __init__(
        self,
        *,
        spawner: InteractiveProcessSpawner | None = None,
        claude_bin: str = "claude",
        terminate_grace: float = _DEFAULT_TERMINATE_GRACE_S,
        allow_bypass: bool = False,
        extra_dirs: Sequence[str] = (),
        isolation: SpawnIsolation | None = None,
        routine_tools: bool = False,
    ) -> None:
        # 🔴 Push guard (BOB-087.E, развязан в bob-c3r.1): the DEFAULT spawner ALWAYS
        # carries a git config in its environment that makes every network push from the
        # live terminal die on a non-existent remote helper. Only the default (real
        # process) boundary is guarded — an injected fake spawns nothing.
        # 🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (правка видимая, а не переписанная задним
        # числом): здесь стояло ``guard_push=allow_bypass``, то есть страховка от
        # нечаянного push включалась ТОЛЬКО ВМЕСТЕ С ОСЛАБЛЕНИЕМ, которое её же и
        # обесценивает, — а в живом конфиге ослабления нет, значит не было и барьера
        # (P0 ``bob-l3t``). Барьер стоит всегда; ``allow_bypass`` влияет РОВНО на
        # allowlist режимов (:mod:`bob.coding.sandbox_policy`) и ни на что больше.
        # 🔴 Credential isolation (BOB-089.C): under ``coder.isolated_clone`` the live
        # terminal ALSO loses sight of the owner's credential helper — the same single
        # seam (:func:`bob.coding.push_guard.guarded_spawn_env`), never a second one.
        self._spawner: InteractiveProcessSpawner = spawner or _ExecInteractiveSpawner(
            isolation=isolation
        )
        self._claude_bin = claude_bin
        self._terminate_grace = terminate_grace
        # Owner-only sandbox relaxations (BOB-087.D2), both inert by default: without
        # ``allow_bypass`` the allowlist is exactly {plan, acceptEdits}, and an empty
        # ``extra_dirs`` appends no ``--add-dir`` — the spawn stays the BOB-083 argv.
        self._allow_bypass = allow_bypass
        self._extra_dirs = tuple(extra_dirs)
        # 🔴 Права инструментов (BOB-088, срез 3). Запрет необратимого приезжает в КАЖДЫЙ
        # спавн, и выключить его нечем — параметра нет, ровно как у push-барьера выше
        # (bob-c3r.1: «страховка, выражаемая одним ключевым словом», в проде оказалась
        # выключенной). Owner-флагом (``coder.pipeline_tools``) включается только ВТОРАЯ
        # половина — явное разрешение рутины конвейера, без которого, по замеру, ``git
        # add`` и ``git commit`` упираются во встроенный гейт CLI.
        self._routine_tools = routine_tools
        self._proc: InteractiveProcess | None = None
        # The claude-assigned session id, captured off the init event as it streams
        # (BOB-087.D1). ``None`` until the init frame is seen; the manager persists it
        # for a later ``--resume`` — the transport itself owns NO session state.
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        """The claude session id seen on the init event, or ``None`` if not yet seen."""
        return self._session_id

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
        allow_once: str = "",
    ) -> None:
        """Spawn the persistent ``claude`` process in ``workdir`` under ``mode``.

        ``resume_session_id`` / ``continue_session`` (BOB-087.D1) opt into resuming a
        prior session; both default OFF, so a caller that does not resume starts a fresh
        session. ``mode`` is checked against the pure allowlist policy —
        ``bypassPermissions`` passes ONLY under the constructor's owner flag
        ``allow_bypass`` (BOB-087.D2).

        🔴 ``allow_once`` (BOB-088, срез 3) — команда, которую владелец только что
        разрешил СЛОВАМИ. Она едет точечным разрешением ровно этого спавна, и вместе с
        ней отходят в сторону накрывающие её шаблоны запрета (иначе запрет победил бы
        разрешение — замерено). ОДНОРАЗОВОСТЬ структурна: это аргумент вызова, состояния
        под него нет, поэтому следующий ``open`` того же раннера снова полон запретов.
        """
        if not is_allowed_mode(mode, allow_bypass=self._allow_bypass):
            raise ClaudeRunError(
                f"mode {mode!r} is not an allowlisted --permission-mode"
            )
        if self._proc is not None:
            raise InteractiveRunError("an interactive process is already open")
        argv = build_interactive_argv(
            self._claude_bin,
            mode=mode,
            resume_session_id=resume_session_id,
            continue_session=continue_session,
            extra_dirs=self._extra_dirs,
            permissions=tool_permission_argv(
                routine=self._routine_tools, allow_once=allow_once
            ),
        )
        self._proc = await self._spawner(argv, cwd=workdir)

    async def feed(self, text: str) -> None:
        """Send ``text`` to the live process as one stream-json ``user`` frame."""
        proc = self._proc
        if proc is None or not proc.alive:
            # Guard: no process, or it has already exited/been closed — drop the
            # frame rather than crash (a steer after the session ended is a no-op).
            return
        payload = encode_user_message(text).encode("utf-8") + b"\n"
        await proc.feed(payload)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        """Async-iterate the process's stdout stream-json events until it exits."""
        proc = self._proc
        if proc is None:
            return
        async for line in proc.read_lines():
            event = parse_event(line)
            if event is None:
                continue
            if self._session_id is None:
                self._session_id = extract_session_id(event)
            yield event

    async def close(self) -> None:
        """Terminate (then kill after a grace) + reap the process (idempotent)."""
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        proc.terminate()
        exited = await proc.wait(timeout=self._terminate_grace)
        if not exited:
            proc.kill()
            await proc.wait()


class _ExecInteractiveProcess:
    """Default process: wraps ``asyncio.subprocess.Process``, no shell."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    async def feed(self, data: bytes) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            return
        stdin.write(data)
        await stdin.drain()

    async def read_lines(self) -> AsyncIterator[str]:
        stdout = self._proc.stdout
        if stdout is None:
            return
        while True:
            try:
                raw = await stdout.readline()
            except ValueError:
                # A single line exceeded ``STREAM_LIMIT`` (LimitOverrunError ->
                # ValueError). The buffer cannot advance past it without re-raising
                # forever, so end the stream gracefully (treat as EOF) rather than crash
                # the output pump — return, do NOT ``continue``.
                logger.warning(
                    "claude stdout line exceeded the %d-byte stream limit; ending read",
                    STREAM_LIMIT,
                )
                return
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace")

    def terminate(self) -> None:
        if self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()

    def kill(self) -> None:
        if self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()

    async def wait(self, *, timeout: float | None = None) -> bool:
        try:
            with contextlib.suppress(ProcessLookupError):
                await asyncio.wait_for(self._proc.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None


class _ExecInteractiveSpawner:
    """Default spawner: ``create_subprocess_exec`` with piped stdio, no shell."""

    def __init__(self, *, isolation: SpawnIsolation | None = None) -> None:
        # Окружение живого терминала — унаследованное ПЛЮС барьер push'а, и ПОД
        # ``isolation`` минус креды owner'а (см. :mod:`bob.coding.push_guard`, включая
        # то, чего эти меры честно НЕ закрывают).
        # 🔴 Барьер здесь БЕЗУСЛОВЕН, и параметра, которым его можно выключить, нет
        # (bob-c3r.1): предыдущая форма ``guard_push=<флаг>`` позволяла выразить «спавн
        # claude без барьера» одним ключевым словом — ровно это и было в проде.
        self._env = guarded_spawn_env(os.environ, active=True, isolation=isolation)

    async def __call__(self, argv: list[str], *, cwd: str) -> InteractiveProcess:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=STREAM_LIMIT,
            env=self._env,
        )
        return _ExecInteractiveProcess(proc)
