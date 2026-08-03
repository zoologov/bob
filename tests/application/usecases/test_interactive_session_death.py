# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты «живой сеанс кончился САМ» — смерть процесса claude (bob-kv4, долг BOB-083/084).

Одна ответственность файла: что делает :class:`InteractiveSessionManager`, когда поток
событий раннера КОНЧИЛСЯ БЕЗ owner-команды (краш ``claude``, его собственный выход,
обрыв чтения stdout). До фикса ``_pump`` не трогал ``_live``: ``active()`` продолжал
отдавать ``True``, ``feed`` ронял реплики owner'а в мёртвый stdin, а интейк-роутер
ПОГЛОЩАЛ ходы — Боб в личке был нем до явного «стоп».

Под тестами четыре вещи (все — наблюдаемые через границу):

* смерть процесса завершает сеанс так же честно, как явный ``stop``: ``active()`` ложно,
  строка в сторе терминальна, эфемерное дерево убрано, ПЕРСИСТЕНТНОЕ — нет,
  ``claude_session_id`` сохранён (сессию можно поднять);
* owner получает ЧЕСТНУЮ реплику, отличную от прощания на его собственный «стоп»;
* ходы перестают поглощаться интейком (``active()`` — тот самый гейт режима);
* 🔴 ИДЕМПОТЕНТНОСТЬ на гонке «процесс умер И owner жмёт стоп»: ровно одно закрытие
  раннера, одна уборка дерева и одна прощальная реплика — без падений.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.interactive_session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_WORKSPACE = "BOB-087"

_INIT_EVENT: Mapping[str, object] = {
    "type": "system",
    "subtype": "init",
    "session_id": "claude-live-9",
}

# Сколько шагов цикла событий даём фоновой перекачке, чтобы она добежала до конца. Все
# сеймы в тестах — мгновенные корутины, поэтому запас заведомо избыточный.
_SETTLE_BUDGET = 200


@dataclass
class _DyingRunner:
    """Раннер, чей процесс УМИРАЕТ САМ: поток событий кончается без ``close``.

    Ровно тот сценарий бага: ``events()`` исчерпывается (EOF stdout мёртвого ребёнка), а
    менеджеру никто ничего не сказал. ``close`` записывается, чтобы проверить, что дохлый
    процесс всё-таки пожат ровно один раз.
    """

    canned: list[Mapping[str, object]] = field(default_factory=list)
    opened: list[tuple[str, str, str | None]] = field(default_factory=list)
    fed: list[str] = field(default_factory=list)
    close_calls: int = 0
    session_id: str | None = None

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
    ) -> None:
        assert continue_session is False
        self.opened.append((workdir, mode, resume_session_id))

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        for event in self.canned:
            yield event
        # 🔴 И ВСЁ: генератор завершается — процесса больше нет.

    async def close(self) -> None:
        self.close_calls += 1


@dataclass
class _KillableRunner(_DyingRunner):
    """Раннер живого процесса, который можно убить СНАРУЖИ (``close``) или изнутри (``die``).

    Нужен для гонки «процесс умер И owner жмёт стоп»: тест сам выбирает момент смерти.
    """

    def __post_init__(self) -> None:
        self._gone = asyncio.Event()

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        for event in self.canned:
            yield event
        await self._gone.wait()

    def die(self) -> None:
        """Процесс кончился сам — поток событий закрывается на следующем шаге цикла."""
        self._gone.set()

    async def close(self) -> None:
        self.close_calls += 1
        self._gone.set()


@dataclass
class _FakeWorktree:
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
        self.pushes.append((path, branch, message))  # 🔴 must NEVER be called
        return True

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)
    saves: list[tuple[str, CodingSessionState]] = field(default_factory=list)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session
        self.saves.append((session.id, session.state))

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        return tuple(s for s in self.sessions.values() if s.branch == branch)


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _ExplodingNotifier(_FakeNotifier):
    """Нотификатор, чей ``send`` падает — сбой транспорта не смеет ронять менеджер."""

    async def send(self, text: str) -> None:
        self.sent.append(text)
        raise RuntimeError("telegram is down")


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
    voice: _FakeNotifier
    runner: _DyingRunner


def _build(
    *,
    runner: _DyingRunner | None = None,
    voice: _FakeNotifier | None = None,
    notifier_wired: bool = True,
    resume_wired: bool = True,
) -> _Rig:
    runner = runner or _DyingRunner()
    worktree = _FakeWorktree()
    store = _FakeStore()
    voice = voice or _FakeNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=_FakeNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        permission_mode="acceptEdits",
        lookup=store if resume_wired else None,
        workspace=worktree if resume_wired else None,
        notifier=voice if notifier_wired else None,
    )
    return _Rig(manager, worktree, store, voice, runner)


async def _settle(predicate: Callable[[], bool]) -> None:
    """Прокрутить цикл событий, пока фоновая перекачка не доведёт дело до ``predicate``."""
    for _ in range(_SETTLE_BUDGET):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("фоновая перекачка не завершилась в отведённый бюджет шагов")


# --- смерть процесса завершает сеанс -----------------------------------------


@pytest.mark.asyncio
async def test_process_death_ends_the_session_so_the_intake_stops_swallowing_turns() -> None:
    # 🔴 bob-kv4: поток событий кончился (процесс умер) — сеанс обязан стать терминальным.
    # ``active()`` — тот самый гейт, по которому интейк-роутер решает поглощать ли ход:
    # пока он True, Боб в личке нем.
    rig = _build()

    opened = await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: not rig.manager.active())

    assert opened.session is not None
    assert rig.manager.active() is False  # обычный Боб в личке вернулся
    saved = rig.store.sessions[opened.session.id]
    assert saved.state is CodingSessionState.CANCELLED
    assert is_terminal(saved.state) is True


@pytest.mark.asyncio
async def test_process_death_reaps_the_runner_and_cleans_the_ephemeral_worktree() -> None:
    # Судьба дерева — по тому же правилу, что у явного ``stop``: эфемерная копия убрана,
    # раннер закрыт (мёртвого ребёнка всё равно нужно пожать — никаких зомби).
    rig = _build()

    await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: bool(rig.worktree.removed))

    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert rig.worktree.pushes == []  # 🔴 INV-2: ни PR, ни пуша


@pytest.mark.asyncio
async def test_process_death_tells_the_owner_honestly_and_not_as_his_own_stop() -> None:
    # 🔴 Owner должен УЗНАТЬ, что сеанс кончился, и понять, что это НЕ его «стоп»:
    # выдавать чужое действие за его — та же неправда, что доклад об уборке сохранённого
    # дерева (BOB-087.D4b).
    rig = _build()

    await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: bool(rig.voice.sent))

    assert rig.voice.sent == [session_voice.interactive_ended()]
    assert session_voice.stopped() not in rig.voice.sent


@pytest.mark.asyncio
async def test_process_death_keeps_the_claude_session_id_for_a_later_resume() -> None:
    # Терминальная строка несёт id claude-сессии — иначе «поднять с телефона» после
    # краша поднимало бы более старую нить (или ничего).
    rig = _build(runner=_DyingRunner(canned=[_INIT_EVENT]))

    opened = await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: not rig.manager.active())

    assert opened.session is not None
    assert rig.store.sessions[opened.session.id].claude_session_id == "claude-live-9"


@pytest.mark.asyncio
async def test_a_fresh_session_can_be_opened_after_the_process_died() -> None:
    # Гвард «одна сессия за раз» не должен залипнуть на трупе.
    rig = _build()
    await rig.manager.open("first task", _OWNER_ID)
    await _settle(lambda: not rig.manager.active())

    outcome = await rig.manager.open("second task", _OWNER_ID)

    assert outcome.ok is True
    assert rig.worktree.created == ["bob/first-task", "bob/second-task"]


# --- персистентный workspace переживает смерть процесса ----------------------


@pytest.mark.asyncio
async def test_process_death_in_a_persistent_workspace_keeps_the_accumulated_tree() -> None:
    # 🔴 Долгоживущее рабочее место НЕ удаляется (в нём накопленная работа) — то же
    # правило, что у ``stop`` возобновлённой сессии (BOB-087.D4b), и реплика идёт ЗА
    # судьбой дерева: про уборку — ни слова, зато зовёт поднять.
    rig = _build(runner=_DyingRunner(canned=[_INIT_EVENT]))

    opened = await rig.manager.open_workspace(_WORKSPACE, "эпик", _OWNER_ID)
    await _settle(lambda: bool(rig.voice.sent))

    assert opened.ok is True
    assert rig.worktree.removed == []  # работа осталась на месте
    assert rig.voice.sent == [session_voice.interactive_ended_persistent()]
    assert opened.session is not None
    saved = rig.store.sessions[opened.session.id]
    assert is_terminal(saved.state) is True
    assert saved.claude_session_id == "claude-live-9"  # можно поднять снова


# --- 🔴 идемпотентность: смерть процесса × явный «стоп» ----------------------


@pytest.mark.asyncio
async def test_an_explicit_stop_after_the_process_already_died_is_not_a_second_closing() -> None:
    # 🔴 Гонка «умер, а потом owner всё-таки жмёт стоп»: второго закрытия, второй уборки
    # и второй реплики быть не должно — и уж точно не падения.
    rig = _build()
    opened = await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: bool(rig.voice.sent))

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.ok is False  # закрывать уже нечего — честная заметка
    assert outcome.message == session_voice.no_session()
    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert rig.voice.sent == [session_voice.interactive_ended()]
    assert opened.session is not None
    terminal_saves = [
        state for sid, state in rig.store.saves if sid == opened.session.id and is_terminal(state)
    ]
    assert terminal_saves == [CodingSessionState.CANCELLED]  # ровно одна терминальная запись


@pytest.mark.asyncio
async def test_an_explicit_stop_never_produces_a_second_death_notice() -> None:
    # Обратный порядок и самый частый случай: owner жмёт «стоп» на ЖИВОМ процессе, поток
    # событий кончается уже ПОСЛЕ этого (close → EOF). Прощание ровно одно — его,
    # «сеанс кончился сам» не досылается.
    rig = _build(runner=_KillableRunner())
    opened = await rig.manager.open("задача", _OWNER_ID)

    outcome = await rig.manager.stop(_OWNER_ID)
    await _settle(lambda: True)

    assert outcome.ok is True
    assert outcome.message == session_voice.stopped()
    assert rig.voice.sent == []  # 🔴 никакой второй реплики от фоновой перекачки
    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert opened.session is not None
    assert rig.store.sessions[opened.session.id].state is CodingSessionState.CANCELLED


@pytest.mark.asyncio
async def test_a_death_landing_inside_the_stop_call_still_closes_exactly_once() -> None:
    # 🔴 Настоящее чередование: процесс умирает РОВНО в тот момент, когда owner жмёт
    # «стоп» (фоновая перекачка просыпается на первом же await внутри ``stop``). Кто бы
    # ни выиграл гонку, инвариант один: одно закрытие, одна уборка, одно прощание.
    runner = _KillableRunner()
    rig = _build(runner=runner)
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    runner.die()  # процесс кончился сам…
    outcome = await rig.manager.stop(_OWNER_ID)  # …и одновременно пришёл «стоп»
    await _settle(lambda: True)

    farewells = [*rig.voice.sent, *([outcome.message] if outcome.ok else [])]
    assert len(farewells) == 1
    assert rig.runner.close_calls == 1
    assert rig.worktree.removed == ["/wt/zadacha"]
    terminal_saves = [
        state for sid, state in rig.store.saves if sid == opened.session.id and is_terminal(state)
    ]
    assert terminal_saves == [CodingSessionState.CANCELLED]


# --- реплика best-effort: сбой транспорта не рушит завершение ----------------


@pytest.mark.asyncio
async def test_a_notifier_fault_never_breaks_the_ending_of_the_session() -> None:
    # Сбой отправки в личку изолирован: сеанс всё равно завершён честно (иначе сбой
    # транспорта вернул бы ровно тот немой режим, который эта беада и закрывает).
    voice = _ExplodingNotifier()
    rig = _build(voice=voice)

    opened = await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: bool(voice.sent))

    assert opened.session is not None
    assert rig.manager.active() is False
    assert rig.store.sessions[opened.session.id].state is CodingSessionState.CANCELLED


@pytest.mark.asyncio
async def test_without_a_wired_notifier_the_death_still_ends_the_session() -> None:
    # Реплика — опциональный seam (композиция может его не завязать); без него сеанс
    # всё равно завершается честно, просто молча.
    rig = _build(notifier_wired=False)

    opened = await rig.manager.open("задача", _OWNER_ID)
    await _settle(lambda: not rig.manager.active())

    assert opened.session is not None
    assert rig.store.sessions[opened.session.id].state is CodingSessionState.CANCELLED
    assert rig.worktree.removed == ["/wt/zadacha"]
