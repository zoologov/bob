# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Harness for the resume / persistent-workspace acceptance scenarios (BOB-087.D).

Wires the REAL «интерактив-2» stack — the real :class:`InteractiveClaudeRunner` over a
fake bidirectional process (never the real ``claude``) → the real
:class:`InteractiveSessionManager` (worktree / store / streamer faked at their ports) →
the real :class:`InteractiveIntakeRouter` — and drives owner-DM turns through the router
exactly the way HandleMessage does. Nothing here reaches into private state: every
observation is taken at a BOUNDARY the production code actually crosses.

What a scenario may assert (:class:`ResumeObservations`):

* **argv + cwd** — the exact token list the runner handed the process spawner, so
  ``--resume <id>`` / ``--permission-mode <mode>`` / ``--add-dir <path>`` are asserted as
  they would appear on a real command line (and the flag-OFF argv is pinned byte-for-byte);
* **ensure vs create vs remove** — whether the work landed in the PERSISTENT workspace
  (``ensure``, reused) or an ephemeral worktree (``create``), and whether any tree was
  ever torn down (a persistent one must not be);
* **consumed** — which turns the interactive mode swallowed and which fell through to the
  ordinary Bob path (owner-only / DM-only / «the mode does not stick»);
* **dm_lines** — what Bob actually said into the owner's DM (the question, the refusal);
* **fed_texts** — what reached the live ``claude``'s stdin (decoded from the stream-json
  frame the runner really wrote), so a command must not leak into the session;
* 🔴 **pushes** — the manager NEVER commits / pushes / opens a PR (INV-2).

The owner-facing config knobs are passed to :func:`build_rig` under their CONFIG names
(``allow_bypass`` / ``extra_dirs`` / ``resume`` / ``permission_mode``); that the runtime
maps ``coder.*`` onto exactly these constructor arguments is pinned separately by
``tests/runtime/wiring/test_coding_sandbox_relaxations.py`` +
``tests/runtime/wiring/test_coding_resume_wiring.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.coding.adapters.interactive_runner import InteractiveClaudeRunner
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.interactive_intake import InteractiveIntakeRouter
from bob.coding.usecases.interactive_session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

__all__ = [
    "BASELINE_ARGV",
    "EPHEMERAL_BRANCH",
    "PRIOR_CLAUDE_SESSION_ID",
    "WORKSPACE",
    "WORKSPACE_BRANCH",
    "WORKSPACE_PATH",
    "ResumeObservations",
    "Rig",
    "Turn",
    "build_rig",
    "live_claude_session_id",
    "prior_session",
    "run_turns",
]

OWNER_ID = 27468732
GUEST_ID = 555

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: The long-lived workspace the scenarios resume, and the branch/path it maps onto.
WORKSPACE = "BOB-087"
WORKSPACE_BRANCH = "bob/epic-bob-087"
WORKSPACE_PATH = "/wt/epic-bob-087"

#: The ephemeral per-task branch an ordinary ``/code -i`` open uses (never persistent).
EPHEMERAL_BRANCH = "bob/fix-the-bug"

#: The claude session id carried by the seeded, already-stopped prior session.
PRIOR_CLAUDE_SESSION_ID = "claude-42"

#: 🔴 The BOB-083 spawn argv, byte-for-byte: with every BOB-087.D knob off, an ordinary
#: interactive open must produce EXACTLY this token list — no resume, no extra dirs.
BASELINE_ARGV: tuple[str, ...] = (
    "claude",
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "acceptEdits",
)


def live_claude_session_id(nth: int) -> str:
    """The session id claude announces on the ``nth`` (1-based) live spawn's init event."""
    return f"claude-live-{nth}"


# --------------------------------------------------------------------------- #
# The subprocess boundary: a fake bidirectional process + spawner
# --------------------------------------------------------------------------- #


def _canned_lines(session_id: str) -> list[str]:
    """One scripted claude run: the init frame (carrying ``session_id``) + a short answer."""
    events: tuple[Mapping[str, object], ...] = (
        {"type": "system", "subtype": "init", "session_id": session_id},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "продолжаю с того места"}]},
        },
        {"type": "result", "subtype": "success", "result": "готово"},
    )
    return [json.dumps(event, ensure_ascii=False) + "\n" for event in events]


class _FakeProcess:
    """A scripted bidirectional process: records fed bytes, terminate, kill.

    ``read_lines`` yields the canned NDJSON lines and then stays open (like a real
    long-lived ``claude``) until ``terminate`` / ``kill``, so the manager's background
    output pump is live between steer replies.
    """

    def __init__(self, lines: Sequence[str]) -> None:
        self.fed: list[bytes] = []
        self.terminated = 0
        self.killed = 0
        self._lines = list(lines)
        self._alive = True
        self._closed = asyncio.Event()
        self.drained = asyncio.Event()

    async def feed(self, data: bytes) -> None:
        self.fed.append(data)

    async def read_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line
        self.drained.set()
        await self._closed.wait()

    def terminate(self) -> None:
        self.terminated += 1
        self._alive = False
        self._closed.set()

    def kill(self) -> None:
        self.killed += 1
        self._alive = False
        self._closed.set()

    async def wait(self, *, timeout: float | None = None) -> bool:
        return not self._alive

    @property
    def alive(self) -> bool:
        return self._alive


class _FakeSpawner:
    """Spawn a fresh fake process per ``open``, recording the argv + cwd it was given."""

    def __init__(self) -> None:
        self.processes: list[_FakeProcess] = []
        self.argvs: list[list[str]] = []
        self.cwds: list[str] = []

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.argvs.append(list(argv))
        self.cwds.append(cwd)
        proc = _FakeProcess(_canned_lines(live_claude_session_id(len(self.processes) + 1)))
        self.processes.append(proc)
        return proc


# --------------------------------------------------------------------------- #
# The session boundaries: worktree / workspace / store+lookup / notifiers / owner
# --------------------------------------------------------------------------- #


@dataclass
class _FakeWorktree:
    """The ephemeral worktree seam AND the persistent ``ensure`` (one adapter, as in prod).

    ``create`` / ``remove`` are the ephemeral per-task pair; ``ensure`` is the long-lived
    workspace that must be REUSED (same path every time) and never removed.
    """

    created: list[str] = field(default_factory=list)
    ensured: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

    async def ensure(self, branch: str) -> str:
        self.ensured.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))  # 🔴 must NEVER be called (INV-2)
        return True

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeStore:
    """The session store AND the narrow by-branch lookup (one adapter, as in production)."""

    sessions: dict[str, CodingSession] = field(default_factory=dict)
    queried: list[str] = field(default_factory=list)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        self.queried.append(branch)
        ordered = sorted(self.sessions.values(), key=lambda s: (s.updated_at, s.id))
        return tuple(s for s in ordered if s.branch == branch)


@dataclass
class _RecordingNotifier:
    """Records the lines that reached the owner's DM (Bob's mode lines OR live output)."""

    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == OWNER_ID


@dataclass
class _MovableClock:
    moment: datetime = _NOW

    def now(self) -> datetime:
        return self.moment


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"is-{counter['n']}"

    return _factory


def prior_session(
    *,
    state: CodingSessionState = CodingSessionState.CANCELLED,
    claude_session_id: str | None = PRIOR_CLAUDE_SESSION_ID,
) -> CodingSession:
    """A previously recorded session of the long-lived workspace (the resume candidate)."""
    return CodingSession(
        id="prev",
        task="эпик BOB-087",
        state=state,
        branch=WORKSPACE_BRANCH,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(hours=2),
        worktree_path=WORKSPACE_PATH,
        claude_session_id=claude_session_id,
    )


# --------------------------------------------------------------------------- #
# The rig + the observations
# --------------------------------------------------------------------------- #


@dataclass
class Rig:
    router: InteractiveIntakeRouter
    manager: InteractiveSessionManager
    spawner: _FakeSpawner
    worktree: _FakeWorktree
    store: _FakeStore
    clock: _MovableClock
    stream_notifier: _RecordingNotifier
    mode_notifier: _RecordingNotifier


def build_rig(
    *,
    sessions: Sequence[CodingSession] = (),
    resume: bool = True,
    allow_bypass: bool = False,
    extra_dirs: Sequence[str] = (),
    permission_mode: str = "acceptEdits",
) -> Rig:
    """Assemble the real interactive stack over fake boundaries, config knobs applied.

    The keyword arguments carry the OWNER-FACING config values (``coder.resume``,
    ``coder.allow_bypass``, ``coder.extra_dirs``, ``coder.permission_mode``) into exactly
    the seams the runtime wiring fills: ``resume`` off leaves the lookup / persistent
    workspace / router-resume seams unwired, so the resume path is structurally absent.
    """
    spawner = _FakeSpawner()
    worktree = _FakeWorktree()
    store = _FakeStore(sessions={session.id: session for session in sessions})
    clock = _MovableClock()
    stream_notifier = _RecordingNotifier()
    mode_notifier = _RecordingNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(
            spawner=spawner, allow_bypass=allow_bypass, extra_dirs=extra_dirs
        ),
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=stream_notifier),
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        permission_mode=permission_mode,
        lookup=store if resume else None,
        workspace=worktree if resume else None,
    )
    router = InteractiveIntakeRouter(
        manager=manager, notifier=mode_notifier, resume=manager if resume else None
    )
    return Rig(
        router=router,
        manager=manager,
        spawner=spawner,
        worktree=worktree,
        store=store,
        clock=clock,
        stream_notifier=stream_notifier,
        mode_notifier=mode_notifier,
    )


@dataclass(slots=True)
class Turn:
    """One DM turn fed to the interactive intake router (optionally after a time jump)."""

    text: str
    is_owner: bool = True
    is_group: bool = False
    sender: int | None = OWNER_ID
    after: timedelta | None = None


@dataclass(slots=True)
class ResumeObservations:
    """What the stack did with the turns — seen only through its boundaries."""

    consumed: list[bool] = field(default_factory=list)
    argvs: list[list[str]] = field(default_factory=list)
    cwds: list[str] = field(default_factory=list)
    spawned: int = 0
    ensured: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)
    dm_lines: list[str] = field(default_factory=list)
    stream_lines: list[str] = field(default_factory=list)
    fed_texts: list[str] = field(default_factory=list)
    terminated: int = 0
    active_after: bool = False


def _decode_stdin_frame(raw: bytes) -> str:
    """Decode ``text`` back out of the stream-json ``user`` frame written to stdin."""
    frame = json.loads(raw.decode("utf-8").rstrip("\n"))
    content = frame["message"]["content"]
    text = content[0]["text"]
    assert isinstance(text, str)
    return text


async def _await_drain(rig: Rig) -> None:
    """Let the background output pump consume the newest process's canned events."""
    if not rig.spawner.processes:
        return
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(rig.spawner.processes[-1].drained.wait(), timeout=1.0)


async def _drive(rig: Rig, turns: Sequence[Turn]) -> ResumeObservations:
    obs = ResumeObservations()
    for turn in turns:
        if turn.after is not None:
            rig.clock.moment = rig.clock.moment + turn.after
        consumed = await rig.router.route(
            text=turn.text,
            sender=turn.sender,
            is_owner=turn.is_owner,
            is_group=turn.is_group,
        )
        obs.consumed.append(consumed)
        await _await_drain(rig)

    # Teardown backstop: no live session may leak past a scenario.
    if rig.manager.active():
        await rig.manager.stop(OWNER_ID)
    obs.active_after = rig.manager.active()

    obs.argvs = [list(argv) for argv in rig.spawner.argvs]
    obs.cwds = list(rig.spawner.cwds)
    obs.spawned = len(rig.spawner.processes)
    obs.terminated = sum(proc.terminated for proc in rig.spawner.processes)
    obs.fed_texts = [
        _decode_stdin_frame(raw) for proc in rig.spawner.processes for raw in proc.fed
    ]
    obs.ensured = list(rig.worktree.ensured)
    obs.created = list(rig.worktree.created)
    obs.removed = list(rig.worktree.removed)
    obs.pushes = list(rig.worktree.pushes)
    obs.dm_lines = list(rig.mode_notifier.sent)
    obs.stream_lines = list(rig.stream_notifier.sent)
    return obs


def run_turns(rig: Rig, turns: Sequence[Turn]) -> ResumeObservations:
    """Drive ``turns`` through the real interactive stack and return the observations."""
    return asyncio.run(_drive(rig, turns))
