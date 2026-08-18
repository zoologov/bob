# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты «отмена посреди спавна не оставляет сироту» — защита в глубину (bob-1qc).

Одна ответственность файла: что остаётся после того, как ход owner'а ОТМЕНИЛИ ровно в
тот момент, когда менеджер спавнил живой ``claude`` (шатдаун, таймаут внешней задачи,
снятие обработчика хода).

Почему это важно, хотя обычный провал спавна давно покрыт: ``except Exception`` НЕ ловит
:class:`asyncio.CancelledError` (он ``BaseException``). Отмена внутри ``runner.open``
раскручивала стек мимо всех веток очистки — запущенный процесс оставался БЕЗ живой
сессии, то есть неостановимым сиротой: ``stop`` его не видит, дерево занято. Поэтому
свёртка спавна живёт в ``finally``, а не в ``except``, и покрывает ОБА конца — и сбой, и
отмену — на всех трёх точках спавна (``open`` / ``open_workspace`` / ``resume``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.interactive.usecases.session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Mapping

    from bob.coding.usecases.coding_assistant import CodingOutcome

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_WORKSPACE = "BOB-087"
_WORKSPACE_BRANCH = "bob/epic-bob-087"


@dataclass
class _HangingRunner:
    """Раннер, чей ``open`` ВИСИТ: процесс уже поднимается, спавн ещё не вернулся.

    Ровно то окно, в котором отмена оставляла сироту. ``entered`` даёт тесту дождаться,
    что мы действительно ВНУТРИ ``open``, а не отменяем ход до спавна.
    """

    close_calls: int = 0
    session_id: str | None = None

    def __post_init__(self) -> None:
        self.entered = asyncio.Event()
        self._never = asyncio.Event()

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
        allow_once: str = "",
    ) -> None:
        assert continue_session is False
        self.entered.set()
        await self._never.wait()  # спавн, который не успевает завершиться

    async def feed(self, text: str) -> None: ...

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        return
        yield  # pragma: no cover — сессия так и не поднялась

    async def close(self) -> None:
        self.close_calls += 1
        self._never.set()


@dataclass
class _ExplodingRunner(_HangingRunner):
    """Раннер, чей спавн ПАДАЕТ — то же правило свёртки, но по обычному сбою."""

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
        allow_once: str = "",
    ) -> None:
        self.entered.set()
        raise RuntimeError("claude failed to spawn")


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    ensured: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

    async def ensure(self, branch: str) -> str:
        self.ensured.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

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

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        return tuple(s for s in self.sessions.values() if s.branch == branch)


@dataclass
class _FakeNotifier:
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


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"is-{counter['n']}"

    return _factory


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    worktree: _FakeWorktree
    store: _FakeStore
    runner: _HangingRunner


def _resumable_candidate() -> CodingSession:
    """Терминальная сессия с id — годный кандидат на подъём (иначе resume не спавнит)."""
    return CodingSession(
        id="past-1",
        task="эпик",
        state=CodingSessionState.CANCELLED,
        branch=_WORKSPACE_BRANCH,
        created_at=_NOW,
        updated_at=_NOW,
        worktree_path="/wt/epic-bob-087",
        claude_session_id="claude-past",
    )


def _build(*, runner: _HangingRunner | None = None) -> _Rig:
    runner = runner or _HangingRunner()
    worktree = _FakeWorktree()
    store = _FakeStore()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=_FakeNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        permission_mode="acceptEdits",
        lookup=store,
        workspace=worktree,
        notifier=_FakeNotifier(),
    )
    return _Rig(manager, worktree, store, runner)


async def _cancel_inside_the_spawn(
    rig: _Rig, call: Coroutine[object, object, CodingOutcome]
) -> None:
    """Дождаться входа в ``runner.open`` и отменить ход прямо там."""
    task = asyncio.ensure_future(call)
    await asyncio.wait_for(rig.runner.entered.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- отмена внутри спавна ------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_open_inside_the_spawn_leaves_no_orphan_process() -> None:
    # 🔴 bob-1qc: отмена летит мимо ``except Exception`` — раннер обязан закрыться всё
    # равно, иначе запущенный процесс остаётся без сессии и его нечем остановить.
    rig = _build()

    await _cancel_inside_the_spawn(rig, rig.manager.open("задача", _OWNER_ID))

    assert rig.runner.close_calls == 1  # 🔴 никаких неостановимых сирот
    assert rig.manager.active() is False
    assert rig.store.sessions == {}


@pytest.mark.asyncio
async def test_cancelling_open_leaves_no_orphan_ephemeral_worktree_either() -> None:
    # Эфемерное дерево уже создано к моменту спавна — свёртка обязана убрать и его
    # (то же правило, что на обычном провале спавна), иначе ветка останется занятой.
    rig = _build()

    await _cancel_inside_the_spawn(rig, rig.manager.open("задача", _OWNER_ID))

    assert rig.worktree.created == ["bob/zadacha"]
    assert rig.worktree.removed == ["/wt/zadacha"]


@pytest.mark.asyncio
async def test_cancelling_open_workspace_closes_the_runner_and_keeps_the_workspace() -> None:
    # Долгоживущее рабочее место НЕ удаляется даже на отмене (в нём накопленная работа),
    # но процесс всё равно не смеет остаться сиротой.
    rig = _build()

    await _cancel_inside_the_spawn(
        rig, rig.manager.open_workspace(_WORKSPACE, "эпик", _OWNER_ID)
    )

    assert rig.runner.close_calls == 1
    assert rig.worktree.ensured == [_WORKSPACE_BRANCH]
    assert rig.worktree.removed == []  # 🔴 накопленная работа не трогается
    assert rig.manager.active() is False


@pytest.mark.asyncio
async def test_cancelling_resume_closes_the_runner_and_keeps_the_workspace() -> None:
    # Третья точка спавна — подъём прошлой сессии; правило то же.
    rig = _build()
    candidate = _resumable_candidate()
    rig.store.sessions[candidate.id] = candidate

    await _cancel_inside_the_spawn(rig, rig.manager.resume(_WORKSPACE, _OWNER_ID))

    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == []
    assert rig.manager.active() is False


# --- обычный сбой спавна сворачивается тем же правилом -------------------------


@pytest.mark.asyncio
async def test_a_failing_spawn_also_closes_the_runner() -> None:
    # Свёртка живёт в ``finally``, поэтому обычный сбой спавна закрывает раннер тем же
    # путём: одна ветка очистки на оба конца, а не две расходящиеся.
    rig = _build(runner=_ExplodingRunner())

    outcome = await rig.manager.open("задача", _OWNER_ID)

    assert outcome.ok is False
    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert rig.manager.active() is False
