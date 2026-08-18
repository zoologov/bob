# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Барьер push доезжает до РЕАЛЬНОГО спавна claude — оба раннера (BOB-087.E, bob-5ao).

Чистое ядро (:mod:`bob.coding.push_guard`) решает, каким быть окружению; здесь
проверяется, что дефолтные спавнеры обоих раннеров это окружение действительно кладут в
``create_subprocess_exec``.

🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (bob-c3r.1; правка видимая, а не переписанная задним
числом). Этот файл утверждал обратное: «при выключенном ``allow_bypass`` (дефолт) спавн
остаётся байт-в-байт прежним, то есть ``env`` в вызов вообще не передаётся» — и это было
верно как ОПИСАНИЕ кода и катастрофично как ГАРАНТИЯ: страховка от нечаянного push
включалась только вместе с owner-ослаблением, которое её же обесценивает, а в живом
конфиге ослабления нет (P0 ``bob-l3t``). Теперь барьер безусловен, и «байт-в-байт
прежний спавн» больше не инвариант — им был отсутствующий барьер.

Настоящий git тут не участвует — эффект барьера на git проверяют
``test_push_guard_real_git.py`` (под ослаблением) и
``test_push_barrier_always_real_git.py`` (без него, через продакшн-проводку); это тест
ПРОВОДКИ.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from bob.coding.adapters.claude_runner import SubprocessClaudeRunner, _ExecStreamRunner
from bob.coding.push_guard import PUSH_GUARD_STUB_URL, PUSH_GUARD_URL_PREFIXES
from bob.interactive.adapters.runner import (
    InteractiveClaudeRunner,
    _ExecInteractiveSpawner,
)

if TYPE_CHECKING:
    import pytest


class _FakeProc:
    """A never-started process stub: enough surface for both spawners to return."""

    def __init__(self) -> None:
        self.returncode: int | None = 0
        self.stdout = None
        self.stdin = None

    def kill(self) -> None:  # pragma: no cover - not reached in these tests
        self.returncode = -9

    async def wait(self) -> int:
        return 0


def _record_spawn(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the kwargs of every ``create_subprocess_exec`` call."""
    seen: list[dict[str, Any]] = []

    async def _fake_exec(*_argv: str, **kwargs: Any) -> _FakeProc:
        seen.append(kwargs)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return seen


def _guard_pairs(env: dict[str, str]) -> set[tuple[str, str]]:
    count = int(env["GIT_CONFIG_COUNT"])
    return {
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)
    }


# --------------------------------------------------------------------------- #
# Дефолт: барьер уже в спавне, без единого owner-флага
# --------------------------------------------------------------------------- #


async def test_oneshot_spawn_carries_the_barrier_without_any_owner_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_spawn(monkeypatch)

    async for _ in _ExecStreamRunner()(["claude"], cwd="/w", timeout=1.0):
        break

    assert _guard_pairs(seen[0]["env"]) == {
        (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
        for prefix in PUSH_GUARD_URL_PREFIXES
    }


async def test_interactive_spawn_carries_the_barrier_without_any_owner_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_spawn(monkeypatch)

    await _ExecInteractiveSpawner()(["claude"], cwd="/w")

    assert _guard_pairs(seen[0]["env"]) == {
        (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
        for prefix in PUSH_GUARD_URL_PREFIXES
    }


def test_default_runners_are_guarded() -> None:
    # Дефолтная сборка раннеров (никаких owner-флагов) уже несёт барьер: выключить его
    # ключевым словом больше нельзя — параметра нет.
    one_shot = SubprocessClaudeRunner()._runner
    interactive = InteractiveClaudeRunner()._spawner
    assert isinstance(one_shot, _ExecStreamRunner)
    assert isinstance(interactive, _ExecInteractiveSpawner)
    assert one_shot._env is not None
    assert interactive._env is not None
    assert _guard_pairs(one_shot._env) == _guard_pairs(interactive._env)


# --------------------------------------------------------------------------- #
# Под owner-ослаблением барьер тоже стоит (развязка двусторонняя)
# --------------------------------------------------------------------------- #


async def test_oneshot_spawn_carries_the_guard_under_allow_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    seen = _record_spawn(monkeypatch)
    runner = SubprocessClaudeRunner(allow_bypass=True)

    async for _ in runner.run("/w", "task", mode="bypassPermissions"):
        break

    env = seen[0]["env"]
    assert env["PATH"] == "/usr/bin"  # окружение НАСЛЕДУЕТСЯ, а не заменяется
    assert _guard_pairs(env) == {
        (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
        for prefix in PUSH_GUARD_URL_PREFIXES
    }


async def test_interactive_spawn_carries_the_guard_under_allow_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    seen = _record_spawn(monkeypatch)
    runner = InteractiveClaudeRunner(allow_bypass=True)

    await runner.open("/w", mode="bypassPermissions")

    env = seen[0]["env"]
    assert env["PATH"] == "/usr/bin"
    assert _guard_pairs(env) == {
        (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
        for prefix in PUSH_GUARD_URL_PREFIXES
    }


async def test_the_guard_follows_neither_the_flag_nor_the_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Барьер не зависит ни от режима прогона (в одной сессии claude может его сменить),
    # ни от owner-флага (bob-c3r.1): он просто стоит.
    seen = _record_spawn(monkeypatch)
    runner = SubprocessClaudeRunner(allow_bypass=True)

    async for _ in runner.run("/w", "task", mode="acceptEdits"):
        break

    assert seen[0]["env"]["GIT_CONFIG_COUNT"] == str(len(PUSH_GUARD_URL_PREFIXES))


async def test_an_injected_runner_is_untouched_by_the_guard() -> None:
    # Барьер живёт на границе процесса (дефолтный спавнер); инъекция подменяет ровно
    # эту границу, поэтому фейки в тестах остаются прежними.
    calls: list[str] = []

    async def _fake_stream(argv: list[str], *, cwd: str, timeout: float) -> Any:
        calls.append(cwd)
        if False:  # pragma: no cover - an empty async generator
            yield ""

    runner = SubprocessClaudeRunner(runner=_fake_stream, allow_bypass=True)
    async for _ in runner.run("/w", "task", mode="bypassPermissions"):
        break

    assert calls == ["/w"]
