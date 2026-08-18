# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Harness for the BOB-088 pipeline acceptance scenarios (С-1 постановка + С-3 разрешения).

Wires the REAL «интерактив-2» stack — the real :class:`InteractiveClaudeRunner` over a
scriptable fake bidirectional process (never the real ``claude``) → the real
:class:`InteractiveSessionManager` (worktree / store / streamer faked at their ports) →
the real :class:`InteractiveIntakeRouter` — and drives owner-DM turns through the router
exactly the way HandleMessage does. Nothing here reaches into private state: every
observation is taken at a BOUNDARY the production code actually crosses.

This is the sibling of :mod:`tests.acceptance.interactive_resume_harness`, but tuned for
the two pieces of behaviour BOB-088 adds and the resume harness does not exercise:

* **С-1 (первый кадр)** — with ``coder.pipeline_prompt`` ON a FRESH session must receive,
  as its very first stdin frame, the owner's task TOGETHER WITH the process instruction
  (``CLAUDE.md`` / ``/coordinator`` / субагенты), and a session raised by ``--resume``
  must NOT receive that frame again. Observed through :attr:`Observations.fed` (decoded
  back out of the stream-json frames actually written to the fake process's stdin) and
  :attr:`Observations.argvs` (whether ``--resume`` rode).
* **С-3 (разрешения)** — a scripted ``permission_denied`` event (the exact NDJSON shape
  captured off the real ``claude`` 2.1.233 in bead ``bob-c3r.3``) makes the manager ask
  the owner IN BOB'S OWN VOICE, in his DM (observed through :attr:`Observations.bob_lines`
  — the manager's own owner-notifier, which is SEPARATE from the GUPPI firehose streamer,
  so С-4's «голос Боба / механика GUPPI» split is visible). The owner's «да» goes through
  the ROUTER (the same path any DM reply takes) and re-enters the SAME claude thread with
  exactly one command allowed (``--resume`` + one ``--allowedTools`` entry, the covering
  ban lifted, everything else still banned). An empty / junk answer does NOT lift the ban.

🔴 The denial question is Bob's, the firehose is GUPPI's: the manager's ``notifier`` and
the streamer's notifier are two DIFFERENT recorders here, so a scenario can assert the
question landed in Bob's channel and NOT in the firehose.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.usecases.intake import InteractiveIntakeRouter
from bob.interactive.usecases.session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

__all__ = [
    "OWNER_ID",
    "PRIOR_CLAUDE_SESSION_ID",
    "WORKSPACE",
    "WORKSPACE_BRANCH",
    "Observations",
    "Rig",
    "Turn",
    "build_rig",
    "denial_stream",
    "prior_session",
    "run_turns",
]

OWNER_ID = 27468732

_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

#: The long-lived workspace a С-1 resume scenario reuses.
WORKSPACE = "BOB-088"
WORKSPACE_BRANCH = "bob/epic-bob-088"

#: The claude session id carried by the seeded, already-stopped prior session (С-1 resume).
PRIOR_CLAUDE_SESSION_ID = "claude-prior-088"

#: The claude session id the scripted live process announces on its init frame — the one
#: a permission re-entry must resume (С-3).
LIVE_CLAUDE_SESSION_ID = "claude-live-088"


# --------------------------------------------------------------------------- #
# Scripted denial stream (the exact NDJSON shape from a real claude 2.1.233 run)
# --------------------------------------------------------------------------- #


def denial_stream(command: str) -> list[str]:
    """One scripted claude run that hits a ban: init → tool_use(command) → denied.

    Matches the protocol recorded in bead ``bob-c3r.3``: the denial event's own
    ``message`` carries the generic CLI string, NOT the command — so «чего Боб хотел»
    must come from the linked ``tool_use`` (by ``tool_use_id``), never from ``message``.
    """
    events: tuple[Mapping[str, object], ...] = (
        {"type": "system", "subtype": "init", "session_id": LIVE_CLAUDE_SESSION_ID},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": command},
                    }
                ],
            },
        },
        {
            "type": "system",
            "subtype": "permission_denied",
            "tool_name": "Bash",
            "tool_use_id": "toolu_1",
            "decision_reason_type": "subcommandResults",
            "message": "This command requires approval",
            "session_id": LIVE_CLAUDE_SESSION_ID,
        },
    )
    return [json.dumps(event, ensure_ascii=False) + "\n" for event in events]


def _plain_stream(session_id: str) -> list[str]:
    """A quiet run: init (carrying ``session_id``) + a short answer, no denial."""
    events: tuple[Mapping[str, object], ...] = (
        {"type": "system", "subtype": "init", "session_id": session_id},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "принято"}]},
        },
        {"type": "result", "subtype": "success", "result": "готово"},
    )
    return [json.dumps(event, ensure_ascii=False) + "\n" for event in events]


# --------------------------------------------------------------------------- #
# The subprocess boundary: a scriptable fake bidirectional process + spawner
# --------------------------------------------------------------------------- #


class _FakeProcess:
    """A scripted bidirectional process: records fed bytes, stays open until closed."""

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


class _ScriptSpawner:
    """Spawn a fake process per ``open`` from a queue of scripts, recording argv + cwd."""

    def __init__(self, scripts: Sequence[Sequence[str]]) -> None:
        self.processes: list[_FakeProcess] = []
        self.argvs: list[list[str]] = []
        self.cwds: list[str] = []
        self._scripts = [list(script) for script in scripts]

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.argvs.append(list(argv))
        self.cwds.append(cwd)
        script = (
            self._scripts.pop(0)
            if self._scripts
            else _plain_stream(f"claude-extra-{len(self.processes) + 1}")
        )
        proc = _FakeProcess(script)
        self.processes.append(proc)
        return proc


# --------------------------------------------------------------------------- #
# The session boundaries: worktree / workspace / store / notifiers / owner
# --------------------------------------------------------------------------- #


@dataclass
class _FakeWorktree:
    """The ephemeral worktree seam AND the persistent ``ensure`` (one adapter, as in prod)."""

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

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.updated_at, s.id))
        return tuple(s for s in ordered if s.branch == branch)


@dataclass
class _RecordingNotifier:
    """Records the lines that reached one DM channel."""

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
    *, claude_session_id: str | None = PRIOR_CLAUDE_SESSION_ID
) -> CodingSession:
    """A previously recorded, already-stopped session of the workspace (resume candidate)."""
    return CodingSession(
        id="prev",
        task="эпик BOB-088",
        state=CodingSessionState.CANCELLED,
        branch=WORKSPACE_BRANCH,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(hours=2),
        worktree_path=f"/wt/{WORKSPACE_BRANCH.split('/', 1)[1]}",
        claude_session_id=claude_session_id,
    )


# --------------------------------------------------------------------------- #
# The rig + the observations
# --------------------------------------------------------------------------- #


@dataclass
class Rig:
    router: InteractiveIntakeRouter
    manager: InteractiveSessionManager
    spawner: _ScriptSpawner
    worktree: _FakeWorktree
    store: _FakeStore
    clock: _MovableClock
    bob_notifier: _RecordingNotifier
    firehose_notifier: _RecordingNotifier
    mode_notifier: _RecordingNotifier


def build_rig(
    *,
    sessions: Sequence[CodingSession] = (),
    scripts: Sequence[Sequence[str]] = (),
    pipeline_prompt: bool = False,
    resume: bool = False,
) -> Rig:
    """Assemble the real interactive stack over fake boundaries, config knobs applied.

    ``pipeline_prompt`` mirrors ``coder.pipeline_prompt`` (С-1: task as the first frame);
    ``resume`` mirrors ``coder.resume`` (the long-lived-workspace / ``/resume`` seams). The
    manager's own owner-notifier (Bob's voice) and the streamer's notifier (the GUPPI
    firehose) are DISTINCT recorders so С-4's split is observable.
    """
    spawner = _ScriptSpawner(scripts)
    worktree = _FakeWorktree()
    store = _FakeStore(sessions={session.id: session for session in sessions})
    clock = _MovableClock()
    bob_notifier = _RecordingNotifier()
    firehose_notifier = _RecordingNotifier()
    mode_notifier = _RecordingNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(spawner=spawner),
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=firehose_notifier),
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        lookup=store if resume else None,
        workspace=worktree if resume else None,
        notifier=bob_notifier,
        pipeline_prompt=pipeline_prompt,
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
        bob_notifier=bob_notifier,
        firehose_notifier=firehose_notifier,
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
class Observations:
    """What the stack did with the turns — seen only through its boundaries."""

    consumed: list[bool] = field(default_factory=list)
    argvs: list[list[str]] = field(default_factory=list)
    spawned: int = 0
    ensured: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)
    #: Text decoded back out of the stream-json frames written to EACH process's stdin,
    #: keyed by spawn order — [[frames of spawn 0], [frames of spawn 1], …].
    fed: list[list[str]] = field(default_factory=list)
    #: What Bob said in his OWN voice (the manager's owner-notifier: the denial question).
    bob_lines: list[str] = field(default_factory=list)
    #: What went out the GUPPI firehose (the live-run streamer).
    firehose_lines: list[str] = field(default_factory=list)
    #: The short mode lines the router emitted (open / stop / permission outcome).
    mode_lines: list[str] = field(default_factory=list)


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


async def _settle(rig: Rig) -> None:
    """Give the manager's background denial/ask work a scheduler turn to run."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _drive(rig: Rig, turns: Sequence[Turn]) -> Observations:
    obs = Observations()
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
        await _settle(rig)

    # Teardown backstop: no live session may leak past a scenario.
    if rig.manager.active():
        await rig.manager.stop(OWNER_ID)

    obs.argvs = [list(argv) for argv in rig.spawner.argvs]
    obs.spawned = len(rig.spawner.processes)
    obs.fed = [
        [_decode_stdin_frame(raw) for raw in proc.fed] for proc in rig.spawner.processes
    ]
    obs.ensured = list(rig.worktree.ensured)
    obs.created = list(rig.worktree.created)
    obs.pushes = list(rig.worktree.pushes)
    obs.bob_lines = list(rig.bob_notifier.sent)
    obs.firehose_lines = list(rig.firehose_notifier.sent)
    obs.mode_lines = list(rig.mode_notifier.sent)
    return obs


def run_turns(rig: Rig, turns: Sequence[Turn]) -> Observations:
    """Drive ``turns`` through the real interactive stack and return the observations."""
    return asyncio.run(_drive(rig, turns))
