# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-subprocess regression net for bob-kv4 — ``claude`` dies on its own.

Why this file exists at all: the unit suite
(``tests/application/usecases/test_interactive_session_death.py``) ends the event stream
by letting an INJECTED fake async generator return — which proves the contract of the
fake, not of the transport. The shipped bug was born exactly there (BOB-084: "fakes do
not model a real transport limit"; BOB-087.D5c repeated the lesson), so the honest proof
is a REAL child process that exits by itself while Bob is holding it.

The stack under test is real end-to-end except the git/telegram boundaries:

    a real OS child (stands in for ``claude``) → the real ``_ExecInteractiveSpawner`` +
    :class:`InteractiveClaudeRunner` (real pipes, real ``readline`` EOF on process death)
    → the real :class:`InteractiveSessionManager`

The child prints ONE stream-json ``init`` frame and one assistant line, then EXITS —
i.e. the process dies WITHOUT anyone calling ``stop``. Against pre-fix code the manager
kept ``_live`` set: ``active()`` stayed ``True``, the intake router went on swallowing the
owner's DM turns and Bob was mute until an explicit «стоп». Against the fix the session
ends terminally, the ephemeral worktree is torn down, the claude session id survives for
a later ``--resume`` and the owner is TOLD, in Bob's voice, that the session ended by
itself.

POSIX-only (a shebang helper stands in for the ``claude`` binary), matching the other
real-tool integration tests in this package (real ``git`` / ``claude`` child / ``gh``).
"""

from __future__ import annotations

import asyncio
import json
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.state import is_terminal
from bob.interactive import voice as interactive_voice
from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.usecases.session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from bob.coding.entities import CodingSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="shebang helper stands in for the claude binary (POSIX only)",
    ),
]

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_CLAUDE_SESSION_ID = "real-child-session-1"

# How long we let the REAL child live, die and the pump notice (generous; the child exits
# immediately, so the wait is normally a couple of loop turns).
_DEATH_TIMEOUT_S = 10.0
_POLL_S = 0.01


#: The two stream-json frames the stand-in child prints before exiting: the ``init`` one
#: (so the claude session id travels the REAL pipe) and one assistant event.
_CHILD_FRAMES: tuple[Mapping[str, object], ...] = (
    {"type": "system", "subtype": "init", "session_id": _CLAUDE_SESSION_ID},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "привет"}]}},
)


def _write_dying_claude(tmp_path: Path) -> str:
    """Create an executable helper that stands in for ``claude`` and DIES on its own.

    It ignores the argv the runner builds, prints the canned stream-json frames and
    exits — the real process death whose stdout EOF the manager must notice.
    """
    payload = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in _CHILD_FRAMES)
    script = tmp_path / "dying_claude.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.stdout.write({payload!r})\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


@dataclass
class _RealDirWorktree:
    """Worktree seam handing out a REAL directory (the child needs a valid ``cwd``)."""

    root: Path
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        return str(self.root)

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        raise AssertionError("the interactive manager must never push")  # 🔴 INV-2

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        return tuple(s for s in self.sessions.values() if not is_terminal(s.state))


@dataclass
class _RecordingNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


@dataclass
class _FakeClock:
    moment: datetime = _NOW

    def now(self) -> datetime:
        return self.moment


async def _wait_until_ended(manager: InteractiveSessionManager, voice: _RecordingNotifier) -> None:
    """Wait for the REAL child's death to travel the pipe and end the session."""
    deadline = asyncio.get_running_loop().time() + _DEATH_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        if not manager.active() and voice.sent:
            return
        await asyncio.sleep(_POLL_S)
    raise AssertionError("the manager never noticed the real process death")


async def test_a_real_claude_child_dying_ends_the_session_and_tells_the_owner(
    tmp_path: Path,
) -> None:
    # Arrange: a REAL child spawned through the runner's own _ExecInteractiveSpawner.
    claude_bin = _write_dying_claude(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    worktree = _RealDirWorktree(root=workdir)
    store = _FakeStore()
    voice = _RecordingNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(claude_bin=claude_bin),
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=_RecordingNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        permission_mode="acceptEdits",
        notifier=voice,
    )

    # Act: open the live session, then simply let the child exit by itself.
    opened = await manager.open("живой сеанс", _OWNER_ID)
    await _wait_until_ended(manager, voice)

    # Assert: the death of a REAL process is a real end of the session.
    assert opened.ok is True
    assert opened.session is not None
    # 🔴 The intake gate is open again — Bob answers his owner in the DM instead of
    # swallowing every turn into a dead stdin.
    assert manager.active() is False
    # The owner HEARD it, and not as if he had asked for the stop himself.
    assert voice.sent == [interactive_voice.interactive_ended()]
    # Terminal row + the id captured off the REAL init frame (a later --resume needs it).
    saved = store.sessions[opened.session.id]
    assert is_terminal(saved.state) is True
    assert saved.claude_session_id == _CLAUDE_SESSION_ID
    # The ephemeral worktree is torn down by the same rule as an explicit stop.
    assert worktree.removed == [str(workdir)]


async def test_an_explicit_stop_after_a_real_child_died_is_a_no_op(tmp_path: Path) -> None:
    # 🔴 Idempotence against a REAL death: the owner types «стоп» a beat too late (he
    # never saw the notice yet). No second closing, no second farewell, no crash.
    claude_bin = _write_dying_claude(tmp_path)
    workdir = tmp_path / "wt"
    workdir.mkdir()
    worktree = _RealDirWorktree(root=workdir)
    voice = _RecordingNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: InteractiveClaudeRunner(claude_bin=claude_bin),
        worktree=worktree,
        store=_FakeStore(),
        streamer_factory=lambda: _DmLiveStreamer(notifier=_RecordingNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        permission_mode="acceptEdits",
        notifier=voice,
    )
    await manager.open("живой сеанс", _OWNER_ID)
    await _wait_until_ended(manager, voice)

    outcome = await manager.stop(_OWNER_ID)

    assert outcome.ok is False
    assert outcome.message == interactive_voice.no_session()
    assert voice.sent == [interactive_voice.interactive_ended()]  # ровно одна реплика
    assert worktree.removed == [str(workdir)]  # ровно одна уборка
