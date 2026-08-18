# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Запрет необратимого доезжает до СПАВНА, а не остаётся в ядре (BOB-088, срез 3).

Предмет: :class:`bob.interactive.adapters.runner.InteractiveClaudeRunner` — граница, за
которой argv превращается в процесс. Чистое ядро прав
(:mod:`bob.interactive.tool_permissions`) проверено отдельно; здесь проверяется то, что
его вердикт ДЕЙСТВИТЕЛЬНО едет в каждый спавн, включая повторный заход по ``--resume``.

🔴 Зачем отдельный файл именно про это (§0.3 п.12): гард, смотрящий только на первый
спавн, остался бы зелёным, если бы повторный заход уходил вообще без запрета — а это и
есть самая правдоподобная дыра, потому что он «и так по разрешению владельца».
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.tool_permissions import tool_permission_argv

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeProcess:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.alive = True

    async def feed(self, data: bytes) -> None:
        self.written.append(data)

    async def read_lines(self) -> AsyncIterator[str]:
        return
        yield ""  # pragma: no cover — держит генератор генератором

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False

    async def wait(self, *, timeout: float | None = None) -> bool:
        return True


class _RecordingSpawner:
    """Подменённая граница процесса: запоминает argv каждого спавна."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.argvs.append(list(argv))
        return _FakeProcess()


def _tail(argv: list[str], flag: str) -> list[str]:
    assert flag in argv, argv
    rest = argv[argv.index(flag) + 1 :]
    return [item for item in rest if not item.startswith("--")]


@pytest.mark.asyncio
async def test_every_spawn_carries_the_denylist() -> None:
    spawner = _RecordingSpawner()
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open("/wt/x", mode="acceptEdits")

    assert _tail(spawner.argvs[0], "--disallowedTools") == _tail(
        tool_permission_argv(), "--disallowedTools"
    )


@pytest.mark.asyncio
async def test_the_re_entry_keeps_everything_except_the_one_approved_command() -> None:
    # 🔴 Повторный заход — не «сессия без правил»: снимается ровно то, что разрешили.
    spawner = _RecordingSpawner()
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open(
        "/wt/x", mode="acceptEdits", resume_session_id="s-1", allow_once="git push origin master"
    )

    argv = spawner.argvs[0]
    denied = _tail(argv, "--disallowedTools")
    assert "Bash(git push origin master)" in _tail(argv, "--allowedTools")
    assert "Bash(git push:*)" not in denied
    assert "Bash(rm:*)" in denied
    assert "Bash(curl:*)" in denied


@pytest.mark.asyncio
async def test_the_routine_list_appears_only_when_the_owner_asked_for_it() -> None:
    quiet = _RecordingSpawner()
    await InteractiveClaudeRunner(spawner=quiet).open("/wt/x", mode="acceptEdits")

    loud = _RecordingSpawner()
    await InteractiveClaudeRunner(spawner=loud, routine_tools=True).open(
        "/wt/x", mode="acceptEdits"
    )

    assert "--allowedTools" not in quiet.argvs[0]
    assert "Bash(uv run pytest:*)" in _tail(loud.argvs[0], "--allowedTools")


@pytest.mark.asyncio
async def test_the_permission_flags_come_after_the_resume_flag() -> None:
    # Порядок задокументирован и стабилен: стратегия возобновления, доп-каталоги, права.
    spawner = _RecordingSpawner()
    runner = InteractiveClaudeRunner(spawner=spawner, extra_dirs=["/srv/docs"])

    await runner.open("/wt/x", mode="acceptEdits", resume_session_id="s-1")

    argv = spawner.argvs[0]
    assert argv.index("--resume") < argv.index("--add-dir") < argv.index("--disallowedTools")


@pytest.mark.asyncio
async def test_a_second_spawn_of_the_same_runner_forgets_the_approval() -> None:
    # 🔴 Одноразовость на границе процесса: разрешение живёт в аргументе ОДНОГО open.
    spawner = _RecordingSpawner()
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open("/wt/x", mode="acceptEdits", allow_once="rm -rf build")
    await runner.close()
    await runner.open("/wt/x", mode="acceptEdits")

    assert "Bash(rm:*)" not in _tail(spawner.argvs[0], "--disallowedTools")
    assert "Bash(rm:*)" in _tail(spawner.argvs[1], "--disallowedTools")
    assert "--allowedTools" not in spawner.argvs[1]
