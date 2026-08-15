# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Сессия начинается с ПОСТАНОВКИ, а не с пустого окна (BOB-088, срез 2).

До этого среза ``runner.open(...)`` вызывался, и в сессию не уходило НИЧЕГО: ``claude``
стартовал с пустым контекстом и ждал, пока owner напишет сам. Здесь под тестами то, что
менеджер делает СРАЗУ после спавна.

🔴 Обе СВЕЖИЕ двери проверяются рядом и нарочно (урок среза 1: дефолт жил в ДВУХ местах, и
правка одного дала бы вакуумный фикс). Их именно две:

* :meth:`~bob.interactive.usecases.session.InteractiveSessionManager.open` — эфемерная
  сессия под задачу (``/code -i <task>``);
* :meth:`~bob.interactive.usecases.session.InteractiveSessionManager.open_workspace` —
  сессия в ДОЛГОЖИВУЩЕМ рабочем месте (``/workspace <name> [task]``). 🔴 Для конвейера
  BOB-088 это ГЛАВНАЯ дверь: эпику нужно место, где работа копится между волнами.

Третья дверь — ``resume`` — постановки НЕ получает, и это тоже утверждается: поднятая
сессия несёт задачу в своём контексте, а повторная постановка велела бы начать эпик заново.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.interactive.pipeline_prompt import pipeline_first_frame
from bob.interactive.usecases.session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_TASK = "BOB-088: довести конвейер до PR"
_WORKSPACE = "BOB-088"
_WORKSPACE_BRANCH = "bob/epic-bob-088"


@dataclass
class _FakeRunner:
    """Fake persistent runner: records the spawn and everything written to stdin."""

    opened: list[tuple[str, str | None]] = field(default_factory=list)
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
        self.opened.append((workdir, resume_session_id))

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        await self._closed.wait()
        return
        yield {}  # pragma: no cover — unreachable, keeps this an async generator

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


@dataclass
class _MuteStdinRunner(_FakeRunner):
    """Раннер, чей stdin умер между спавном и постановкой (процесс упал сразу)."""

    async def feed(self, text: str) -> None:
        raise RuntimeError("broken pipe")


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
        raise AssertionError("живой сеанс не пушит (INV-2)")

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
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


@dataclass
class _FakeLookup:
    sessions: tuple[CodingSession, ...] = ()

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        return tuple(s for s in self.sessions if s.branch == branch)


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"is-{counter['n']}"

    return _factory


def _stopped_session() -> CodingSession:
    """Терминальная сессия того же workspace — кандидат на подъём."""
    return CodingSession(
        id="prev",
        task=_TASK,
        state=CodingSessionState.CANCELLED,
        branch=_WORKSPACE_BRANCH,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(hours=2),
        worktree_path=f"/wt/{_WORKSPACE_BRANCH.split('/', 1)[1]}",
        claude_session_id="claude-42",
    )


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    runner: _FakeRunner
    worktree: _FakeWorktree
    store: _FakeStore


def _build(
    *,
    pipeline_prompt: bool,
    runner: _FakeRunner | None = None,
    sessions: tuple[CodingSession, ...] = (),
) -> _Rig:
    runner = runner or _FakeRunner()
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
        lookup=_FakeLookup(sessions=sessions),
        workspace=worktree,
        pipeline_prompt=pipeline_prompt,
    )
    return _Rig(manager, runner, worktree, store)


# --------------------------------------------------------------------------- #
# Флаг ON: обе СВЕЖИЕ двери начинают сессию постановкой
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_ephemeral_session_starts_with_the_task_instead_of_an_empty_window() -> None:
    rig = _build(pipeline_prompt=True)

    outcome = await rig.manager.open(_TASK, _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.fed == [pipeline_first_frame(_TASK)]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_long_lived_workspace_door_starts_with_the_task_too() -> None:
    # 🔴 ВТОРАЯ дверь, и для эпика — главная: правка одной из двух дала бы вакуумный фикс
    # (урок среза 1, где дефолт жил в двух местах).
    rig = _build(pipeline_prompt=True)

    outcome = await rig.manager.open_workspace(_WORKSPACE, _TASK, _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.fed == [pipeline_first_frame(_TASK)]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_task_is_put_before_the_owner_says_anything() -> None:
    # Порядок и есть смысл: постановка — ПЕРВЫЙ кадр, реплики owner'а идут после неё.
    rig = _build(pipeline_prompt=True)

    await rig.manager.open(_TASK, _OWNER_ID)
    await rig.manager.feed("а теперь покажи план")

    assert rig.runner.fed[0] == pipeline_first_frame(_TASK)
    assert rig.runner.fed[1] == "а теперь покажи план"

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_resumed_session_is_not_told_to_start_over() -> None:
    # 🔴 Поднятая сессия несёт задачу в своём контексте; повторная постановка велела бы
    # начать эпик заново — поверх накопленной работы.
    rig = _build(pipeline_prompt=True, sessions=(_stopped_session(),))

    outcome = await rig.manager.resume(_WORKSPACE, _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.opened == [(f"/wt/{_WORKSPACE_BRANCH.split('/', 1)[1]}", "claude-42")]
    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# Флаг OFF (дефолт): спавн байт-в-байт прежний
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_without_the_flag_nothing_is_put_into_the_session_at_all() -> None:
    rig = _build(pipeline_prompt=False)

    await rig.manager.open(_TASK, _OWNER_ID)
    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_without_the_flag_the_workspace_door_is_silent_too() -> None:
    rig = _build(pipeline_prompt=False)

    await rig.manager.open_workspace(_WORKSPACE, _TASK, _OWNER_ID)
    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_manager_built_without_the_knob_puts_nothing() -> None:
    # 🔴 Дефолт читается СБОРКОЙ БЕЗ АРГУМЕНТА, а не значением, переданным в тесте: мощная
    # способность приезжает выключенной (конвенция BOB-076).
    runner = _FakeRunner()
    worktree = _FakeWorktree()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=_FakeStore(),
        streamer_factory=lambda: _DmLiveStreamer(notifier=_FakeNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )

    await manager.open(_TASK, _OWNER_ID)
    assert runner.fed == []

    await manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# Края
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_blank_task_puts_nothing_and_the_session_still_opens() -> None:
    # Пустой постановки не бывает: «Задача от owner'а:» без задачи модель додумала бы сама.
    rig = _build(pipeline_prompt=True)

    outcome = await rig.manager.open_workspace(_WORKSPACE, "   ", _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_session_that_cannot_be_given_its_task_is_not_left_running() -> None:
    # 🔴 Тот же шов, что у сбоя спавна (bob-1qc): всё, что упало ДО живой сессии,
    # сворачивает спавн — раннер закрыт, эфемерное дерево убрано, owner слышит отказ,
    # а не молчание и не «сессия открыта» поверх мёртвого процесса.
    rig = _build(pipeline_prompt=True, runner=_MuteStdinRunner())

    outcome = await rig.manager.open(_TASK, _OWNER_ID)

    assert outcome.ok is False
    assert rig.manager.active() is False
    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/bob-088-dovesti-konveyer-do-pr"]
    assert rig.store.sessions == {}
