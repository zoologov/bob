# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Упёрся в запрет — спросил владельца словами — вернулся и сделал (BOB-088, срез 3).

Здесь под тестами ПОВЕДЕНИЕ собранного менеджера живого сеанса, а не форма кода: в поток
приходит настоящий (снятый с живого прогона) кадр ``system/permission_denied``, и дальше
проверяется то, что видит владелец, — реплика в личку, а на его «да» — повторный заход в
ТУ ЖЕ нить claude с точечным разрешением ровно одной команды.

🔴 Почему тут вообще есть про что спрашивать (замер, протокол в комментарии беады
``bob-c3r.3``): в этой версии CLI отказ получает не только то, что запретили мы, но и
``git add``, ``git commit``, ``python3 -c`` — встроенным гейтом. До этого среза такой отказ
не значил ничего: поток его проглатывал (рендер отдаёт ``None`` на ``system``), модель
получала ошибку, а владелец не узнавал НИЧЕГО. Конвейер молча останавливался.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.state import is_terminal
from bob.interactive.denial_voice import (
    permission_declined,
    permission_lifted,
    permission_unreachable,
)
from bob.interactive.pipeline_prompt import permission_retry_frame
from bob.interactive.usecases.session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_STRANGER_ID = 5
_NOW = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)
_TASK = "BOB-088: довести конвейер до PR"
_CLAUDE_SESSION = "6f893fe1-cf3f-4e83-b15c-8270c90cdf58"
_COMMAND = "git push origin bob/bob-088"


def _init_event() -> dict[str, Any]:
    return {"type": "system", "subtype": "init", "session_id": _CLAUDE_SESSION}


def _tool_use_event(command: str, *, tool_use_id: str = "toolu_1") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ],
        },
    }


def _denied_event(*, tool_use_id: str = "toolu_1") -> dict[str, Any]:
    # Дословная форма живого прогона (см. беаду): message НЕ несёт команду.
    return {
        "type": "system",
        "subtype": "permission_denied",
        "tool_name": "Bash",
        "tool_use_id": tool_use_id,
        "decision_reason_type": "other",
        "decision_reason": "This command requires approval",
        "message": "This command requires approval",
        "session_id": _CLAUDE_SESSION,
    }


@dataclass
class _FakeRunner:
    """Раннер, который отдаёт заранее заготовленный поток и помнит свой спавн."""

    script: list[Mapping[str, object]] = field(default_factory=list)
    opened: list[tuple[str, str | None, str]] = field(default_factory=list)
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
        allow_once: str = "",
    ) -> None:
        self.opened.append((workdir, resume_session_id, allow_once))

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        for event in self.script:
            yield event
        await self._closed.wait()

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


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
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.arrived = asyncio.Event()

    async def send(self, text: str) -> None:
        self.sent.append(text)
        self.arrived.set()


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


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    runners: list[_FakeRunner]
    notifier: _FakeNotifier
    store: _FakeStore
    worktree: _FakeWorktree


def _build(*scripts: list[Mapping[str, object]]) -> _Rig:
    """Собрать менеджер, чьи ПОСЛЕДОВАТЕЛЬНЫЕ спавны отдают заготовленные потоки."""
    queued = list(scripts)
    runners: list[_FakeRunner] = []
    notifier = _FakeNotifier()
    worktree = _FakeWorktree()
    store = _FakeStore()

    def _factory() -> _FakeRunner:
        script = queued.pop(0) if queued else []
        runner = _FakeRunner(script=list(script))
        runners.append(runner)
        return runner

    manager = InteractiveSessionManager(
        runner_factory=_factory,
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=_FakeNotifier()),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        notifier=notifier,
    )
    return _Rig(manager, runners, notifier, store, worktree)


async def _wait_for_the_question(rig: _Rig) -> str:
    await asyncio.wait_for(rig.notifier.arrived.wait(), timeout=1)
    return rig.notifier.sent[-1]


# --------------------------------------------------------------------------- #
# Боб спрашивает — живой речью, в личку
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_denial_reaches_the_owner_as_a_question_in_his_own_dm() -> None:
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    question = await _wait_for_the_question(rig)

    assert _COMMAND in question
    assert question.rstrip().endswith("?")
    # 🔴 Служебная английская строка CLI в реплику Боба не попадает.
    assert "approval" not in question

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_question_offers_no_button_and_no_slash_command() -> None:
    # Решение владельца от 2026-08-15: только слова.
    rig = _build([_init_event(), _tool_use_event("rm -rf .worktrees/x"), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    question = (await _wait_for_the_question(rig)).replace("rm -rf .worktrees/x", "")

    assert "/" not in question
    assert "нажми" not in question.lower()

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_bob_does_not_ask_twice_before_he_is_answered() -> None:
    # Отказы сыплются пачкой (модель пробует варианты); человек так не переспрашивает.
    rig = _build(
        [
            _init_event(),
            _tool_use_event(_COMMAND, tool_use_id="toolu_1"),
            _denied_event(tool_use_id="toolu_1"),
            _tool_use_event("git push --force origin master", tool_use_id="toolu_2"),
            _denied_event(tool_use_id="toolu_2"),
        ]
    )

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    await asyncio.sleep(0)

    assert len(rig.notifier.sent) == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_an_ordinary_stream_says_nothing_to_the_owner() -> None:
    rig = _build([_init_event(), _tool_use_event("uv run pytest")])

    await rig.manager.open(_TASK, _OWNER_ID)
    await asyncio.sleep(0)

    assert rig.notifier.sent == []

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# «Да» — повторный заход в ТУ ЖЕ нить с точечным разрешением
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_yes_re_enters_the_same_claude_thread_with_that_one_command_allowed() -> None:
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()], [_init_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    outcome = await rig.manager.resolve_pending_permission("да", _OWNER_ID)

    assert outcome is not None
    assert outcome.ok is True
    assert outcome.message == permission_lifted(_COMMAND)
    # 🔴 ВТОРОЙ раннер: та же нить claude (--resume) и ровно одна разрешённая команда.
    assert len(rig.runners) == 2
    assert rig.runners[1].opened == [
        ("/wt/bob-088-dovesti-konveyer-do-pr", _CLAUDE_SESSION, _COMMAND)
    ]
    # И сессии сказано вернуться к тому месту, иначе подъём ничего не повторит.
    assert rig.runners[1].fed == [permission_retry_frame(_COMMAND)]
    assert rig.manager.active() is True

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_old_process_is_not_left_running_beside_the_new_one() -> None:
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()], [_init_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    await rig.manager.resolve_pending_permission("да", _OWNER_ID)

    assert rig.runners[0].close_calls == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_lift_is_one_shot_and_the_next_spawn_asks_for_nothing() -> None:
    # 🔴 Одноразовость доказывается СЛЕДУЮЩИМ спавном, а не намерением.
    rig = _build(
        [_init_event(), _tool_use_event(_COMMAND), _denied_event()],
        [_init_event()],
        [_init_event()],
    )

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    await rig.manager.resolve_pending_permission("да", _OWNER_ID)
    await rig.manager.stop(_OWNER_ID)
    await rig.manager.open(_TASK, _OWNER_ID)

    assert rig.runners[2].opened == [("/wt/bob-088-dovesti-konveyer-do-pr", None, "")]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_work_of_the_session_survives_the_re_entry() -> None:
    # Эфемерное дерево НЕ убирается при повторном заходе: в нём работа этой же сессии.
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()], [_init_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    await rig.manager.resolve_pending_permission("да", _OWNER_ID)

    assert rig.worktree.removed == []

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# «Нет» и края
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_no_spawns_nothing_and_says_so_shortly() -> None:
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()], [_init_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    outcome = await rig.manager.resolve_pending_permission("нет", _OWNER_ID)

    assert outcome is not None
    assert outcome.message == permission_declined()
    assert len(rig.runners) == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_turn_that_is_not_an_answer_is_left_to_the_session() -> None:
    # Вопрос снимается, а реплика идёт обычным путём — в stdin живой сессии.
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)

    assert await rig.manager.resolve_pending_permission("покажи дифф", _OWNER_ID) is None

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_stranger_cannot_answer_the_owners_question() -> None:
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)

    assert await rig.manager.resolve_pending_permission("да", _STRANGER_ID) is None
    assert len(rig.runners) == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_yes_after_the_session_died_is_answered_honestly() -> None:
    # 🔴 Названная граница: доразрешить на месте нельзя, а возвращаться уже некуда.
    rig = _build([_init_event(), _tool_use_event(_COMMAND), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    await rig.manager.stop(_OWNER_ID)

    outcome = await rig.manager.resolve_pending_permission("да", _OWNER_ID)

    assert outcome is not None
    assert outcome.message == permission_unreachable()
    assert len(rig.runners) == 1


@pytest.mark.asyncio
async def test_a_yes_without_a_known_claude_thread_is_answered_honestly_too() -> None:
    # Без init-кадра нити нет: поднимать нечего, и Боб не делает вид, что поднял.
    rig = _build([_tool_use_event(_COMMAND), _denied_event()])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_the_question(rig)
    outcome = await rig.manager.resolve_pending_permission("да", _OWNER_ID)

    assert outcome is not None
    assert outcome.message == permission_unreachable()
    assert len(rig.runners) == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_nothing_pending_means_the_turn_is_not_ours() -> None:
    rig = _build([_init_event()])

    await rig.manager.open(_TASK, _OWNER_ID)

    assert await rig.manager.resolve_pending_permission("да", _OWNER_ID) is None

    await rig.manager.stop(_OWNER_ID)
