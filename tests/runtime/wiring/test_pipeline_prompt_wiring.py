# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Гард ПОВЕДЕНИЯ собранной проводки: сессия начинается с задачи (BOB-088, срез 2).

Проверяется не форма кода и не значение поля, а ЧТО УЕХАЛО В СЕССИЮ, когда владелец
поднял её на своём конфиге (§0.3 п.12). Реальны здесь: настоящий :class:`ConfigLoader`,
настоящий продакшн-строитель ``_build_interactive_session`` (он один читает флаг
``coder.pipeline_prompt``), настоящий менеджер и настоящее доменное ядро текста. Фейками
подменены ровно ТРИ границы, которые иначе полезли бы наружу теста: процесс ``claude``,
git (клон рабочего места — 5 с и 145 МБ на дверь) и SQLite.

🔴 ДВЕРЕЙ У СВЕЖЕЙ СЕССИИ ДВЕ, и обе проверяются здесь — это прямой урок среза 1, где
дефолт жил в ДВУХ местах и правка одного дала бы вакуумный фикс. Эпик открывается
``/workspace <name> <task>`` (``open_workspace``), а не ``/code -i`` (``open``), поэтому
гард, знающий только про вторую, зеленел бы ровно на том случае, ради которого весь
BOB-088 и делается.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.state import is_terminal
from bob.infrastructure.config.loader import ConfigLoader
from bob.interactive.pipeline_prompt import pipeline_first_frame
from bob.interactive.usecases.teardown import SessionTeardown
from bob.runtime.wiring.coding import _build_interactive_session

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


# --------------------------------------------------------------------------- #
# Три подменённые границы: процесс claude, git, SQLite
# --------------------------------------------------------------------------- #


@dataclass
class _RecordingRunner:
    """Процесс ``claude``, из которого нам нужно одно: что уехало в его stdin."""

    fed: list[str] = field(default_factory=list)
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
        return None

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        # Живой процесс держит stdout открытым, пока не умрёт: иначе перекачка тут же
        # завершила бы сеанс сама и утащила в тест лишний путь.
        await self._closed.wait()
        return
        yield {}  # pragma: no cover — недостижимо, держит функцию асинхронным генератором

    async def close(self) -> None:
        self._closed.set()


@dataclass
class _FakeTree:
    """Рабочее место без git: настоящее завело бы КЛОН (5 с и 145 МБ на дверь)."""

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


class _StubBot:
    """Бот-заглушка: на проводке в него не отправляется ничего."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 15, tzinfo=UTC)


class _StubConnection:
    """Соединение-заглушка: продакшн-стор её держит, но мы его подменяем."""


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


# --------------------------------------------------------------------------- #
# Сборка: настоящий загрузчик → настоящий строитель → подмена трёх границ
# --------------------------------------------------------------------------- #


def _loaded(tmp_path: Path, coder_lines: str = "") -> Mapping[str, object]:
    """Конфиг НАСТОЯЩЕГО загрузчика из yaml формы живого ``config/bob.yaml``.

    ``coder_lines`` дописывается в секцию ``coder``; пусто → ключа ``pipeline_prompt``
    в конфиге НЕТ ВОВСЕ — это и есть дефолтный случай.
    """
    path = tmp_path / "bob.yaml"
    path.write_text(
        "coder:\n"
        "  enabled: true\n"
        "  interactive: true\n"
        "  resume: true\n"  # долгоживущее место — та самая вторая дверь
        f"  clone_root: {tmp_path / 'clones'}\n" + coder_lines,
        encoding="utf-8",
    )
    return ConfigLoader(yaml_path=path, env={}).load()


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    runner: _RecordingRunner


def _wired(tmp_path: Path, coder_lines: str = "") -> _Rig:
    """Собрать менеджер ПРОДАКШН-ПУТЁМ и подменить процесс / git / SQLite."""
    manager = _build_interactive_session(
        _loaded(tmp_path, coder_lines),
        repo=cast("SqliteConnection", _StubConnection()),
        authorizer=cast("Authorizer", _StubAuthorizer()),
        bot=_bot(),
        stream_bot=_bot(),
        owner_id=_OWNER_ID,
        clock=cast("Clock", _StubClock()),
    )
    assert manager is not None
    runner = _RecordingRunner()
    tree = _FakeTree()
    store = _FakeStore()
    clock = _StubClock()
    manager._runner_factory = lambda: cast("InteractiveRunner", runner)
    manager._worktree = cast("Worktree", tree)
    manager._workspace = cast("PersistentWorkspace", tree)
    manager._store = cast("CodingSessionStore", store)
    manager._teardown = SessionTeardown(
        worktree=cast("Worktree", tree),
        store=cast("CodingSessionStore", store),
        clock=cast("Clock", clock),
    )
    return _Rig(manager, runner)


# --------------------------------------------------------------------------- #
# Флаг включён: обе свежие двери начинают сессию задачей
# --------------------------------------------------------------------------- #

_ON = "  pipeline_prompt: true\n"


@pytest.mark.asyncio
async def test_the_ephemeral_door_hands_claude_the_task(tmp_path: Path) -> None:
    rig = _wired(tmp_path, _ON)

    outcome = await rig.manager.open(_TASK, _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.fed == [pipeline_first_frame(_TASK)]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_long_lived_workspace_door_hands_claude_the_task(tmp_path: Path) -> None:
    # 🔴 ВТОРОЙ ВХОД. Эпик — а BOB-088 весь про эпик — открывается именно этой дверью.
    rig = _wired(tmp_path, _ON)

    outcome = await rig.manager.open_workspace(_WORKSPACE, _TASK, _OWNER_ID)

    assert outcome.ok is True
    assert rig.runner.fed == [pipeline_first_frame(_TASK)]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_what_reaches_claude_is_the_process_instruction_not_just_the_task(
    tmp_path: Path,
) -> None:
    # Проводка обязана донести КАНОНИЧЕСКИЙ кадр, а не «что-нибудь непустое»: без указания
    # на процесс сессия снова превращается в «claude что-то делает».
    rig = _wired(tmp_path, _ON)

    await rig.manager.open(_TASK, _OWNER_ID)

    assert len(rig.runner.fed) == 1
    frame = rig.runner.fed[0]
    assert _TASK in frame
    assert "CLAUDE.md" in frame
    assert "/coordinator" in frame
    assert "СУБАГЕНТАМИ" in frame

    await rig.manager.stop(_OWNER_ID)


# --------------------------------------------------------------------------- #
# Ключа нет / явный отказ: спавн байт-в-байт прежний
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_config_without_the_key_puts_nothing_into_the_ephemeral_session(
    tmp_path: Path,
) -> None:
    rig = _wired(tmp_path)

    await rig.manager.open(_TASK, _OWNER_ID)

    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_config_without_the_key_puts_nothing_into_the_workspace_session(
    tmp_path: Path,
) -> None:
    rig = _wired(tmp_path)

    await rig.manager.open_workspace(_WORKSPACE, _TASK, _OWNER_ID)

    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_an_explicit_off_is_respected(tmp_path: Path) -> None:
    rig = _wired(tmp_path, "  pipeline_prompt: false\n")

    await rig.manager.open(_TASK, _OWNER_ID)

    assert rig.runner.fed == []

    await rig.manager.stop(_OWNER_ID)
