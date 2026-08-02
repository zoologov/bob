# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты возобновления сессии в долгоживущем workspace (BOB-087.D3).

«Поднять с телефона нашу эпик-сессию и продолжить»: owner явной командой просит поднять
приостановленную работу, Боб СНАЧАЛА переспрашивает, и только после «да» поднимает
``claude --resume <id>`` в ПЕРСИСТЕНТНОМ worktree. Здесь под тестами три предохранителя:

* 🔴 **owner-only + подтверждение** — не-owner не получает ни вопроса, ни сессии;
  сама команда ``/resume`` НИЧЕГО не спавнит (ни worktree, ни процесса) — поднимает
  только явное «да» в окне TTL; «нет», молчание, посторонняя реплика и протухшее
  подтверждение сессию не поднимают;
* 🔴 **никакого live-attach** — при живой сессии возобновление отказывает, а кандидатом
  может быть только ТЕРМИНАЛЬНАЯ сессия (политика :func:`select_resumable`);
* 🔴 **персистентный workspace не удаляется** — ``stop`` возобновлённой сессии НЕ зовёт
  ``remove`` (иначе накопленная работа стёрлась бы), в отличие от эфемерной сессии
  ``open``; провал спавна на resume тоже ничего не удаляет.

Плюс: менеджер по-прежнему не пушит/не мержит/не открывает PR.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.entities import CodingSession
from bob.coding.resume_policy import CONFIRMATION_TTL
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.interactive_session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.usecases.coding_assistant import CodingOutcome

_OWNER_ID = 27468732
_STRANGER_ID = 555
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_WORKSPACE = "BOB-087"
_WORKSPACE_BRANCH = "bob/epic-bob-087"


@dataclass
class _FakeInteractiveRunner:
    """Fake persistent runner recording the spawn (incl. the resume id) and the steer."""

    canned: list[Mapping[str, object]] = field(default_factory=list)
    opened: list[tuple[str, str, str | None]] = field(default_factory=list)
    fed: list[str] = field(default_factory=list)
    close_calls: int = 0
    session_id: str | None = None

    def __post_init__(self) -> None:
        self._closed = asyncio.Event()

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
    ) -> None:
        assert continue_session is False  # D3 resumes BY ID, never «the latest»
        self.opened.append((workdir, mode, resume_session_id))

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        for event in self.canned:
            yield event
        await self._closed.wait()

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


@dataclass
class _ExplodingRunner(_FakeInteractiveRunner):
    """A runner whose spawn fails — the persistent workspace must survive it."""

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
    ) -> None:
        raise RuntimeError("claude failed to spawn")


@dataclass
class _FakeWorktree:
    """Ephemeral worktree seam + the persistent ``ensure`` (same adapter in production)."""

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
        self.pushes.append((path, branch, message))  # must NEVER be called
        return True

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeLookup:
    """Narrow resumable-session lookup: records the queried branch, returns canned rows."""

    sessions: tuple[CodingSession, ...] = ()
    queried: list[str] = field(default_factory=list)

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        self.queried.append(branch)
        return tuple(s for s in self.sessions if s.branch == branch)


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


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


def _stopped_session(
    *,
    sid: str = "prev",
    branch: str = _WORKSPACE_BRANCH,
    state: CodingSessionState = CodingSessionState.CANCELLED,
    claude_session_id: str | None = "claude-42",
    updated_at: datetime = _NOW - timedelta(hours=2),
) -> CodingSession:
    return CodingSession(
        id=sid,
        task="эпик BOB-087",
        state=state,
        branch=branch,
        created_at=_NOW - timedelta(days=1),
        updated_at=updated_at,
        worktree_path="/wt/epic-bob-087",
        claude_session_id=claude_session_id,
    )


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    worktree: _FakeWorktree
    store: _FakeStore
    notifier: _FakeNotifier
    runner: _FakeInteractiveRunner
    lookup: _FakeLookup
    clock: _MovableClock


def _build(
    *,
    runner: _FakeInteractiveRunner | None = None,
    sessions: tuple[CodingSession, ...] = (),
    with_resume: bool = True,
) -> _Rig:
    runner = runner or _FakeInteractiveRunner()
    worktree = _FakeWorktree()
    store = _FakeStore()
    notifier = _FakeNotifier()
    lookup = _FakeLookup(sessions=sessions)
    clock = _MovableClock()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=notifier),
        owner=_FakeOwner(),
        clock=clock,
        id_factory=_ids(),
        permission_mode="acceptEdits",
        lookup=lookup if with_resume else None,
        workspace=worktree if with_resume else None,
    )
    return _Rig(manager, worktree, store, notifier, runner, lookup, clock)


async def _confirm(rig: _Rig, text: str = "да") -> CodingOutcome | None:
    return await rig.manager.resolve_pending_resume(text, _OWNER_ID)


# --- propose_resume: Bob asks FIRST, spawns nothing ---------------------------


@pytest.mark.asyncio
async def test_propose_asks_for_confirmation_and_spawns_nothing() -> None:
    rig = _build(sessions=(_stopped_session(),))

    outcome = await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    assert outcome.ok is True
    # 🔴 The command alone raises NOTHING: no worktree, no process, no session row.
    assert rig.worktree.ensured == []
    assert rig.worktree.created == []
    assert rig.runner.opened == []
    assert rig.store.sessions == {}
    assert rig.manager.active() is False
    # The question names the workspace and when that session was (owner may be on a phone).
    assert _WORKSPACE in outcome.message
    assert "10:00" in outcome.message  # updated_at was two hours before «now» (12:00)
    assert "?" in outcome.message
    # It looked at the WORKSPACE branch, not an ephemeral per-task one.
    assert rig.lookup.queried == [_WORKSPACE_BRANCH]


@pytest.mark.asyncio
async def test_propose_without_a_candidate_is_an_honest_refusal() -> None:
    rig = _build(sessions=())

    outcome = await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    assert outcome.ok is False
    assert _WORKSPACE in outcome.message
    # And a later «да» must not resurrect anything — there is no pending question.
    assert await _confirm(rig) is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_propose_ignores_a_live_session_candidate() -> None:
    # 🔴 No live-attach: an INTERACTIVE row on the same branch is not a candidate.
    rig = _build(sessions=(_stopped_session(state=CodingSessionState.INTERACTIVE),))

    outcome = await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    assert outcome.ok is False
    assert await _confirm(rig) is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_propose_from_a_non_owner_is_silently_refused() -> None:
    rig = _build(sessions=(_stopped_session(),))

    outcome = await rig.manager.propose_resume(_WORKSPACE, _STRANGER_ID)

    assert outcome.ok is False
    assert outcome.message == ""  # 🔴 silent refusal — a stranger learns nothing
    assert rig.lookup.queried == []  # not even a lookup runs for a non-owner
    # A stranger cannot arm a question, and cannot confirm one either.
    assert await rig.manager.resolve_pending_resume("да", _STRANGER_ID) is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_propose_while_a_session_is_live_is_refused() -> None:
    # 🔴 One session at a time: with a live terminal, resume never even asks.
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.open("другая задача", _OWNER_ID)

    outcome = await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    assert outcome.ok is False
    assert outcome.message
    assert await _confirm(rig) is None

    await rig.manager.stop(_OWNER_ID)


# --- confirmation raises the session ------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_resumes_in_the_persistent_workspace_by_id() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    outcome = await _confirm(rig)

    assert outcome is not None
    assert outcome.ok is True
    # 🔴 PERSISTENT workspace: ``ensure`` (reuse), never the ephemeral ``create``.
    assert rig.worktree.ensured == [_WORKSPACE_BRANCH]
    assert rig.worktree.created == []
    # Spawned in that tree with --resume <the persisted claude session id>.
    assert rig.runner.opened == [("/wt/epic-bob-087", "acceptEdits", "claude-42")]
    assert rig.manager.active() is True
    # A NEW live row is persisted (the old terminal one is history, never rewritten).
    assert outcome.session is not None
    saved = rig.store.sessions[outcome.session.id]
    assert saved.state is CodingSessionState.INTERACTIVE
    assert saved.branch == _WORKSPACE_BRANCH
    assert saved.claude_session_id == "claude-42"
    assert saved.id != "prev"

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_confirmation_picks_the_freshest_stopped_session() -> None:
    rig = _build(
        sessions=(
            _stopped_session(
                sid="old", claude_session_id="claude-old", updated_at=_NOW - timedelta(days=2)
            ),
            _stopped_session(
                sid="new", claude_session_id="claude-new", updated_at=_NOW - timedelta(hours=1)
            ),
        )
    )
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    await _confirm(rig)

    assert rig.runner.opened == [("/wt/epic-bob-087", "acceptEdits", "claude-new")]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_resumed_session_streams_output_to_the_dm() -> None:
    runner = _FakeInteractiveRunner(
        canned=[{"type": "result", "subtype": "success", "result": "продолжаю"}]
    )
    rig = _build(runner=runner, sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    await _confirm(rig)
    for _ in range(10):  # let the background pump drain the canned event
        await asyncio.sleep(0)

    assert rig.notifier.sent

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_steer_after_resume_reaches_the_live_process() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    await _confirm(rig)

    await rig.manager.feed("продолжаем с тестов")

    assert rig.runner.fed == ["продолжаем с тестов"]

    await rig.manager.stop(_OWNER_ID)


# --- the confirmation gate: everything else does NOT resume -------------------


@pytest.mark.asyncio
async def test_rejection_cancels_and_raises_nothing() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    outcome = await rig.manager.resolve_pending_resume("нет", _OWNER_ID)

    assert outcome is not None
    assert outcome.ok is True
    assert outcome.message  # a short honest line
    assert rig.worktree.ensured == []
    assert rig.runner.opened == []
    assert rig.manager.active() is False
    # And the question is gone — a later «да» resumes nothing.
    assert await _confirm(rig) is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_any_other_message_drops_the_pending_question() -> None:
    # 🔴 The question must not stick: an unrelated reply clears it (and is NOT consumed),
    # so a «да» that answers something else entirely never raises a session.
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    passed_through = await rig.manager.resolve_pending_resume(
        "а что там по погоде", _OWNER_ID
    )

    assert passed_through is None
    assert await _confirm(rig) is None
    assert rig.runner.opened == []
    assert rig.manager.active() is False


@pytest.mark.asyncio
async def test_hedged_yes_is_not_a_confirmation() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    outcome = await rig.manager.resolve_pending_resume("да, но сначала покажи дифф", _OWNER_ID)

    assert outcome is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_expired_confirmation_does_not_resume() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    rig.clock.moment = _NOW + CONFIRMATION_TTL + timedelta(seconds=1)

    outcome = await _confirm(rig)

    assert outcome is None
    assert rig.worktree.ensured == []
    assert rig.runner.opened == []
    assert rig.manager.active() is False


@pytest.mark.asyncio
async def test_confirmation_just_inside_the_window_still_resumes() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    rig.clock.moment = _NOW + CONFIRMATION_TTL

    outcome = await _confirm(rig)

    assert outcome is not None
    assert outcome.ok is True

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_confirmation_without_a_question_does_nothing() -> None:
    rig = _build(sessions=(_stopped_session(),))

    assert await _confirm(rig) is None
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_a_stranger_cannot_answer_the_owners_question() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    assert await rig.manager.resolve_pending_resume("да", _STRANGER_ID) is None
    assert rig.runner.opened == []
    # The owner's own question survives a stranger's interference.
    outcome = await _confirm(rig)
    assert outcome is not None
    assert outcome.ok is True

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_direct_resume_from_a_non_owner_is_refused() -> None:
    rig = _build(sessions=(_stopped_session(),))

    outcome = await rig.manager.resume(_WORKSPACE, _STRANGER_ID)

    assert outcome.ok is False
    assert outcome.message == ""
    assert rig.worktree.ensured == []
    assert rig.runner.opened == []


@pytest.mark.asyncio
async def test_resume_is_inert_when_the_seams_are_not_wired() -> None:
    # Flag OFF → the manager is built without the lookup/workspace seams: resume is
    # structurally unavailable (nothing to ensure, nothing to look up).
    rig = _build(sessions=(_stopped_session(),), with_resume=False)

    proposed = await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    resumed = await rig.manager.resume(_WORKSPACE, _OWNER_ID)

    assert proposed.ok is False
    assert resumed.ok is False
    assert rig.worktree.ensured == []
    assert rig.runner.opened == []
    assert await _confirm(rig) is None


# --- 🔴 the persistent workspace is never deleted ------------------------------


@pytest.mark.asyncio
async def test_stopping_a_resumed_session_keeps_the_persistent_workspace() -> None:
    # 🔴 THE data-loss guard: the accumulated workspace survives ``stop`` — unlike the
    # ephemeral per-task worktree, it is NEVER removed.
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    resumed = await _confirm(rig)
    assert resumed is not None

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.ok is True
    assert rig.worktree.removed == []  # 🔴 the work is still there
    assert rig.manager.active() is False
    assert outcome.session is not None
    assert rig.store.sessions[outcome.session.id].state is CodingSessionState.CANCELLED


@pytest.mark.asyncio
async def test_stopping_an_ephemeral_session_still_removes_its_worktree() -> None:
    # The persistent exception must not leak into the ordinary ephemeral flow.
    rig = _build()

    await rig.manager.open("fix bug", _OWNER_ID)
    await rig.manager.stop(_OWNER_ID)

    assert rig.worktree.created == ["bob/fix-bug"]
    assert rig.worktree.removed == ["/wt/fix-bug"]


@pytest.mark.asyncio
async def test_stopping_a_resumed_session_tells_the_owner_the_work_survived() -> None:
    # 🔴 BOB-087.D4b (честность голоса): дерево сохраняется — значит и РЕПЛИКА обязана
    # говорить правду. Ассерт на то, что owner ПРОЧИТАЕТ (исходящий текст), а не на
    # ``worktree.removed``: именно взгляд только на внутреннее состояние проглядел баг.
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    await _confirm(rig)

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.message == session_voice.stopped_persistent()
    assert "убрал" not in outcome.message.casefold()


@pytest.mark.asyncio
async def test_stopping_an_ephemeral_session_still_reports_the_cleanup() -> None:
    # Эфемерный путь не меняется: копия действительно убрана — так Боб и говорит.
    rig = _build()
    await rig.manager.open("fix bug", _OWNER_ID)

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.message == session_voice.stopped()


@pytest.mark.asyncio
async def test_stop_persists_the_new_claude_session_id_of_a_resumed_session() -> None:
    # The resumed run gets its own claude id; persisting it keeps the chain resumable.
    rig = _build(
        runner=_FakeInteractiveRunner(session_id="claude-next"),
        sessions=(_stopped_session(),),
    )
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    await _confirm(rig)

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.session is not None
    assert rig.store.sessions[outcome.session.id].claude_session_id == "claude-next"


@pytest.mark.asyncio
async def test_a_failed_resume_spawn_keeps_the_workspace_and_leaves_no_session() -> None:
    rig = _build(runner=_ExplodingRunner(), sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)

    outcome = await _confirm(rig)

    assert outcome is not None
    assert outcome.ok is False
    assert outcome.message
    assert rig.worktree.removed == []  # 🔴 a failed spawn must NOT delete the work
    assert rig.manager.active() is False
    assert rig.store.sessions == {}


# --- 🔴 never a PR / merge / push ---------------------------------------------


@pytest.mark.asyncio
async def test_resumed_session_never_pushes_or_opens_a_pr() -> None:
    rig = _build(sessions=(_stopped_session(),))
    await rig.manager.propose_resume(_WORKSPACE, _OWNER_ID)
    await _confirm(rig)
    await rig.manager.feed("правь")
    await rig.manager.stop(_OWNER_ID)

    assert rig.worktree.pushes == []
