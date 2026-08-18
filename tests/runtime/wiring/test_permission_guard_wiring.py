# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Гард ПОВЕДЕНИЯ собранной проводки: запрет, вопрос и возвращение (BOB-088, срез 3).

Проверяется не форма кода и не значение поля, а то, ЧТО ПРОИСХОДИТ, когда владелец
поднял сессию на своём конфиге (§0.3 п.12). Реальны здесь: настоящий
:class:`ConfigLoader`, настоящий продакшн-строитель ``_build_interactive_session``,
настоящий :class:`InteractiveClaudeRunner` (значит argv собирает продакшн-код), настоящий
интейк-роутер, настоящий менеджер и все доменные ядра. Подменены ровно ДВЕ границы:
процесс ``claude`` (вместо него — сценарий из строк NDJSON, снятых с живого прогона) и
git/SQLite (клон стоит 5 с и 145 МБ на дверь).

🔴 Три входа, каждый из которых по отдельности сделал бы работу вакуумной:

1. **argv спавна** — запрет должен доехать до процесса, а не остаться в ядре;
2. **вторая дверь** — ``/workspace`` (та самая, которой открывается эпик), а не только
   ``/code -i``;
3. **роутер** — при живом сеансе ЛЮБОЙ плоский текст владельца уходит в stdin ``claude``,
   поэтому его «да» без перехвата прочитал бы claude, а не Боб. Менеджер при этом
   остался бы зелёным в своих тестах: его метод существует и работает — его просто никто
   не зовёт.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.state import is_terminal
from bob.infrastructure.config.loader import ConfigLoader
from bob.interactive.pipeline_prompt import permission_retry_frame
from bob.interactive.usecases.teardown import SessionTeardown
from bob.runtime.wiring.coding import (
    _build_interactive_intake,
    _build_interactive_session,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from pathlib import Path

    from bob.coding.entities import CodingSession
    from bob.coding.ports import (
        CodingSessionStore,
        InteractiveRunner,
        PersistentWorkspace,
        Worktree,
    )
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.interactive.usecases.session import InteractiveSessionManager
    from bob.kernel.ports import Clock
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732
_TASK = "BOB-088: довести конвейер до PR"
_WORKSPACE = "BOB-088"
_CLAUDE_SESSION = "6f893fe1-cf3f-4e83-b15c-8270c90cdf58"
_COMMAND = "git push origin bob/bob-088"

# Строки NDJSON ровно той формы, что пришла с настоящего claude 2.1.233 (протокол —
# в комментарии беады bob-c3r.3): init, вызов инструмента, отказ без команды в message.
_STREAM = [
    json.dumps({"type": "system", "subtype": "init", "session_id": _CLAUDE_SESSION}),
    json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": _COMMAND},
                    }
                ],
            },
        }
    ),
    json.dumps(
        {
            "type": "system",
            "subtype": "permission_denied",
            "tool_name": "Bash",
            "tool_use_id": "toolu_1",
            "decision_reason_type": "other",
            "decision_reason": "This command requires approval",
            "message": "This command requires approval",
            "session_id": _CLAUDE_SESSION,
        }
    ),
]


# --------------------------------------------------------------------------- #
# Подменённые границы: процесс claude, git, SQLite, бот
# --------------------------------------------------------------------------- #


class _FakeProcess:
    """Процесс, отдающий заготовленные строки stdout и помнящий свой stdin."""

    def __init__(self, lines: list[str]) -> None:
        self.fed: list[bytes] = []
        self.alive = True
        self._lines = lines
        self._closed = asyncio.Event()

    async def feed(self, data: bytes) -> None:
        self.fed.append(data)

    async def read_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line
        await self._closed.wait()

    def terminate(self) -> None:
        self.alive = False
        self._closed.set()

    def kill(self) -> None:
        self.terminate()

    async def wait(self, *, timeout: float | None = None) -> bool:
        return True


class _RecordingSpawner:
    """Граница процесса: помнит argv КАЖДОГО спавна и отдаёт заготовленный поток."""

    def __init__(self, scripts: list[list[str]]) -> None:
        self.argvs: list[list[str]] = []
        self.processes: list[_FakeProcess] = []
        self._scripts = scripts

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.argvs.append(list(argv))
        script = self._scripts.pop(0) if self._scripts else []
        process = _FakeProcess(script)
        self.processes.append(process)
        return process


@dataclass
class _FakeTree:
    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def ensure(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        raise AssertionError("живой сеанс не пушит (INV-2)")

    async def remove(self, path: str) -> None:
        return None


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
        return ()


class _RecordingBot:
    """Бот: помнит, ЧТО и В КАКОЙ чат ушло (это и есть «владелец прочитал»)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.arrived = asyncio.Event()

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
    ) -> None:
        self.sent.append((chat_id, str(getattr(rich_message, "markdown", rich_message))))
        self.arrived.set()

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> None:
        self.sent.append((chat_id, text))
        self.arrived.set()


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 15, tzinfo=UTC)


class _StubConnection:
    """Соединение-заглушка: продакшн-стор её держит, но мы его подменяем."""


# --------------------------------------------------------------------------- #
# Сборка: настоящий загрузчик → настоящий строитель → подмена двух границ
# --------------------------------------------------------------------------- #


def _loaded(tmp_path: Path, coder_lines: str = "") -> Mapping[str, object]:
    path = tmp_path / "bob.yaml"
    path.write_text(
        "coder:\n"
        "  enabled: true\n"
        "  interactive: true\n"
        "  resume: true\n"
        f"  clone_root: {tmp_path / 'clones'}\n" + coder_lines,
        encoding="utf-8",
    )
    return ConfigLoader(yaml_path=path, env={}).load()


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    router: object
    spawner: _RecordingSpawner
    bot: _RecordingBot


def _wired(
    tmp_path: Path, coder_lines: str = "", *, scripts: list[list[str]] | None = None
) -> _Rig:
    """Собрать проводку продакшн-путём; подменены только процесс, git и SQLite."""
    config = _loaded(tmp_path, coder_lines)
    bot = _RecordingBot()
    manager = _build_interactive_session(
        config,
        repo=cast("SqliteConnection", _StubConnection()),
        authorizer=cast("Authorizer", _StubAuthorizer()),
        bot=cast("BotLike", bot),
        stream_bot=cast("BotLike", bot),
        owner_id=_OWNER_ID,
        clock=cast("Clock", _StubClock()),
    )
    assert manager is not None
    router = _build_interactive_intake(
        config, manager=manager, bot=cast("BotLike", bot), owner_id=_OWNER_ID
    )
    assert router is not None
    spawner = _RecordingSpawner(scripts or [])
    tree = _FakeTree()
    store = _FakeStore()
    # 🔴 Раннер остаётся ПРОДАКШН-раннером: подменяется только граница процесса, поэтому
    # argv собирает тот самый код, который поднимает claude у владельца.
    real_factory = manager._runner_factory

    def _factory() -> InteractiveRunner:
        runner = real_factory()
        runner._spawner = spawner  # type: ignore[attr-defined]
        return runner

    manager._runner_factory = _factory
    manager._worktree = cast("Worktree", tree)
    manager._workspace = cast("PersistentWorkspace", tree)
    manager._store = cast("CodingSessionStore", store)
    manager._teardown = SessionTeardown(
        worktree=cast("Worktree", tree),
        store=cast("CodingSessionStore", store),
        clock=cast("Clock", _StubClock()),
    )
    return _Rig(manager, router, spawner, bot)


def _denied(argv: list[str]) -> list[str]:
    assert "--disallowedTools" in argv, argv
    tail = argv[argv.index("--disallowedTools") + 1 :]
    return [item for item in tail if not item.startswith("--")]


async def _wait_for_a_line(rig: _Rig) -> str:
    await asyncio.wait_for(rig.bot.arrived.wait(), timeout=2)
    return rig.bot.sent[-1][1]


# --------------------------------------------------------------------------- #
# 1. Запрет доезжает до процесса — на конфиге, где НИЧЕГО про это не написано
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_session_the_owner_opened_cannot_do_the_irreversible(tmp_path: Path) -> None:
    rig = _wired(tmp_path)

    await rig.manager.open(_TASK, _OWNER_ID)

    denied = _denied(rig.spawner.argvs[0])
    for pattern in ("Bash(git push:*)", "Bash(rm:*)", "Bash(curl:*)", "Bash(gh pr merge:*)"):
        assert pattern in denied, denied

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_epic_door_is_guarded_too(tmp_path: Path) -> None:
    # 🔴 ВТОРАЯ ДВЕРЬ: эпик открывается ``/workspace``, а не ``/code -i``.
    rig = _wired(tmp_path)

    await rig.manager.open_workspace(_WORKSPACE, _TASK, _OWNER_ID)

    assert "Bash(rm:*)" in _denied(rig.spawner.argvs[0])

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_routine_of_the_pipeline_rides_only_when_the_owner_switched_it_on(
    tmp_path: Path,
) -> None:
    quiet = _wired(tmp_path)
    await quiet.manager.open(_TASK, _OWNER_ID)
    await quiet.manager.stop(_OWNER_ID)

    loud = _wired(tmp_path, "  pipeline_tools: true\n")
    await loud.manager.open(_TASK, _OWNER_ID)
    await loud.manager.stop(_OWNER_ID)

    assert "--allowedTools" not in quiet.spawner.argvs[0]
    assert "Bash(uv run pytest:*)" in loud.spawner.argvs[0]
    # 🔴 И разрешение рутины НЕ отменяет запрета необратимого.
    assert "Bash(git push:*)" in _denied(loud.spawner.argvs[0])


@pytest.mark.asyncio
async def test_an_explicit_off_keeps_the_ban_anyway(tmp_path: Path) -> None:
    # Флаг владельца выключает РАЗРЕШЕНИЕ рутины; запрет необратимого им не управляется.
    rig = _wired(tmp_path, "  pipeline_tools: false\n")

    await rig.manager.open(_TASK, _OWNER_ID)

    assert "--allowedTools" not in rig.spawner.argvs[0]
    assert "Bash(rm:*)" in _denied(rig.spawner.argvs[0])

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# 2. Отказ доходит до владельца ЖИВОЙ РЕЧЬЮ, в его личку
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_owner_hears_about_the_denial_in_his_own_words(tmp_path: Path) -> None:
    rig = _wired(tmp_path, scripts=[_STREAM])

    await rig.manager.open(_TASK, _OWNER_ID)
    question = await _wait_for_a_line(rig)

    chat_id, _text = rig.bot.sent[-1]
    assert chat_id == _OWNER_ID  # личка владельца, а не групповой топик
    assert _COMMAND in question
    assert question.rstrip().endswith("?")
    # 🔴 Служебная английская строка CLI внутрь речи Боба не попадает.
    assert "approval" not in question
    # Ни кнопок, ни слеш-команды в ответ.
    assert "/" not in question.replace(_COMMAND, "")

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# 3. «Да» владельца доходит до БОБА, а не в stdin claude
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_owners_yes_returns_the_session_with_that_command_allowed(
    tmp_path: Path,
) -> None:
    rig = _wired(tmp_path, scripts=[_STREAM, [_STREAM[0]]])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_a_line(rig)

    # 🔴 Ход идёт ЧЕРЕЗ РОУТЕР — тем же путём, каким приходит любая реплика из лички.
    consumed = await rig.router.route(  # type: ignore[attr-defined]
        text="да", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is True
    assert len(rig.spawner.argvs) == 2, "повторного захода не случилось"
    second = rig.spawner.argvs[1]
    at = second.index("--resume")
    assert second[at : at + 2] == ["--resume", _CLAUDE_SESSION]
    assert f"Bash({_COMMAND})" in second
    assert "Bash(git push:*)" not in _denied(second)
    # 🔴 Всё остальное необратимое в ТОМ ЖЕ заходе по-прежнему запрещено.
    assert "Bash(rm:*)" in _denied(second)
    # И в поднятую нить ушёл кадр возвращения, иначе повторять было бы нечему.
    fed = b"".join(rig.spawner.processes[1].fed).decode()
    retry = permission_retry_frame(_COMMAND)
    assert retry is not None
    assert retry.splitlines()[0] in fed

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_yes_does_not_leak_into_the_stdin_of_claude(tmp_path: Path) -> None:
    # 🔴 Ровно тот второй вход: без перехвата «да» прочитал бы claude, а вопрос завис бы.
    rig = _wired(tmp_path, scripts=[_STREAM, [_STREAM[0]]])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_a_line(rig)
    await rig.router.route(  # type: ignore[attr-defined]
        text="да", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    first_stdin = b"".join(rig.spawner.processes[0].fed).decode()
    assert '"да"' not in first_stdin

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_next_session_is_forbidden_everything_again(tmp_path: Path) -> None:
    # 🔴 Одноразовость снятия — на собранной проводке, а не только в ядре.
    rig = _wired(tmp_path, scripts=[_STREAM, [_STREAM[0]], []])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_a_line(rig)
    await rig.router.route(  # type: ignore[attr-defined]
        text="да", sender=_OWNER_ID, is_owner=True, is_group=False
    )
    await rig.manager.stop(_OWNER_ID)
    await rig.manager.open(_TASK, _OWNER_ID)

    third = rig.spawner.argvs[2]
    assert "Bash(git push:*)" in _denied(third)
    assert "--allowedTools" not in third

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_no_leaves_the_session_where_it_was(tmp_path: Path) -> None:
    rig = _wired(tmp_path, scripts=[_STREAM])

    await rig.manager.open(_TASK, _OWNER_ID)
    await _wait_for_a_line(rig)
    consumed = await rig.router.route(  # type: ignore[attr-defined]
        text="нет", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is True
    assert len(rig.spawner.argvs) == 1

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_denial_with_no_call_behind_it_does_not_borrow_the_words_of_the_cli(
    tmp_path: Path,
) -> None:
    # 🔴 Кадр вызова до перекачки не дошёл (обрыв, перезапуск) — и тут соблазн подставить
    # в реплику ``message`` события выглядит безобидно: строка ведь осмысленная. Только
    # это АНГЛИЙСКАЯ строка CLI внутри русской речи Боба — тот самый дефект rule_voice.
    lonely = [_STREAM[0], _STREAM[2]]
    rig = _wired(tmp_path, scripts=[lonely])

    await rig.manager.open(_TASK, _OWNER_ID)
    line = await _wait_for_a_line(rig)

    assert "approval" not in line
    assert "This command" not in line
    # И это честная реплика «сам снять не могу», а не пустой вопрос.
    assert "?" not in line

    await rig.manager.stop(_OWNER_ID)
