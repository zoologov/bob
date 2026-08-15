# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_workspace`` — переключатель «worktree или КЛОН» (BOB-089, срез A).

Решение читает ОДНА функция — ``_uses_isolated_clone``, и клон в ней ДЕФОЛТ (bob-c3r.1).
OFF-путь (ЯВНЫЙ отказ владельца) доказывается РАВЕНСТВОМ сборки — тип адаптера и его
аргументы, — а не «похожестью»: если бы флаг ушёл в OFF-путь хоть одним аргументом, эти
тесты покраснели бы.

🔴 ИСПРАВЛЕНО ПО ФАКТУ 2026-08-15 (bob-c3r.1; правка видимая). Здесь стояло «(default
OFF)», и четыре теста ниже закрепляли ИМЕННО ЭТО: конфиг без ключа отдавал linked worktree
владельца. Дефолтом стала безопасная дорога, поэтому «выключено» отныне пишется ЯВНО — и
тесты спрашивают именно про явный отказ.

Оба адаптера подставляются под одни и те же порты, поэтому use-case'ы (гейтед-ассистент и
менеджер интерактива) не знают, во что приземляются; здесь же проверено, что оба
композиционных вызова действительно ходят через этот переключатель, а не мимо.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.git_clone import GitClone
from bob.coding.adapters.git_worktree import GitWorktree
from bob.coding.ports import PersistentWorkspace, Worktree
from bob.runtime.config import _REPO_ROOT
from bob.runtime.wiring import coding as coding_wiring
from bob.runtime.wiring.coding import (
    _build_coding_assistant,
    _build_interactive_session,
    _build_spawn_isolation,
    _build_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder — the adapters are assembled, never sent through, at wiring."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 5, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


class _StubRecorder:
    async def record_self_action(self, *args: object, **kwargs: object) -> None: ...


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _coder_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "notifier_bot": _bot(),
        "stream_bot": _bot(),
        "chat_id": -100123,
        "topic_id": None,
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
        "recorder": cast("SelfActionRecorder", _StubRecorder()),
        "work_journal": cast("WorkJournalRecorder", _StubRecorder()),
    }


def _interactive_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": _bot(),
        "stream_bot": _bot(),
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def _workspace_of(assembled: object) -> object:
    return assembled._worktree  # type: ignore[attr-defined]  # композиция под тестом


# --------------------------------------------------------------------------- #
# OFF — прежний linked worktree, доказано РАВЕНСТВОМ (тип + аргументы)
# --------------------------------------------------------------------------- #


def test_flag_off_builds_the_previous_worktree_adapter() -> None:
    workspace = _build_workspace({"isolated_clone": False})

    assert type(workspace) is GitWorktree
    assert workspace._worktree_root == Path(".worktrees")


def test_a_config_without_the_key_takes_the_safe_road_instead() -> None:
    # 🔴 Парный к тесту выше: отсутствие ключа больше НЕ означает «прежнее место». Раньше
    # тут проверялось обратное (``{}`` → GitWorktree), и это было содержанием P0 bob-l3t.
    assert type(_build_workspace({})) is GitClone


def test_flag_off_still_honours_the_configured_worktree_root() -> None:
    workspace = _build_workspace({"isolated_clone": False, "worktree_root": "/srv/trees"})

    assert type(workspace) is GitWorktree
    assert workspace._worktree_root == Path("/srv/trees")


# --------------------------------------------------------------------------- #
# ON — отдельный клон
# --------------------------------------------------------------------------- #


def test_flag_on_builds_the_clone_adapter_rooted_at_the_repository() -> None:
    # 🔴 Относительный ``clone_root`` привязан к КОРНЮ РЕПОЗИТОРИЯ, а не к текущему
    # каталогу (ревью bob-a6b.6, M4): ``source`` абсолютен, поэтому при ``cwd ≠ корень``
    # клоны уезжали бы не туда, а первым это заметил бы не тест, а прод — ровно урок
    # BOB-087.D5b, который и был про относительный путь.
    workspace = _build_workspace({"isolated_clone": True})

    assert type(workspace) is GitClone
    assert workspace._clone_root == _REPO_ROOT / ".clones"
    assert workspace._source == _REPO_ROOT.resolve()
    assert workspace._fork_url == ""  # форк не настроен → у клона нет remote'а вовсе


def test_a_relative_clone_root_does_not_follow_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    workspace = _build_workspace({"isolated_clone": True, "clone_root": "work/clones"})

    assert type(workspace) is GitClone
    assert workspace._clone_root == _REPO_ROOT / "work/clones"


def test_the_spawn_environment_is_rooted_at_the_repository_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Тот же вопрос для файлов изоляции: ``<clone_root>/.spawn-env`` — сосед клонов, и
    # уехать в чужой каталог по воле ``cwd`` он не должен. Корень репозитория подменён на
    # одноразовый, чтобы тест не писал файлы в рабочее дерево.
    monkeypatch.setattr(coding_wiring, "_REPO_ROOT", tmp_path / "repo")
    monkeypatch.chdir(tmp_path)

    isolation = _build_spawn_isolation({"isolated_clone": True, "clone_root": ".clones"})

    assert isolation is not None
    assert isolation.config_global.startswith(str(tmp_path / "repo" / ".clones" / ".spawn-env"))
    assert not (tmp_path / ".clones").exists()  # ничего не легло рядом с cwd


def test_flag_on_points_the_clone_at_the_configured_fork() -> None:
    workspace = _build_workspace(
        {
            "isolated_clone": True,
            "clone_root": "/srv/clones",
            "fork_url": "git@github.com:bobiverse-dev/bob.git",
        }
    )

    assert type(workspace) is GitClone
    assert workspace._clone_root == Path("/srv/clones")
    assert workspace._fork_url == "git@github.com:bobiverse-dev/bob.git"


def test_both_adapters_satisfy_the_two_workplace_ports() -> None:
    # Подмена возможна только потому, что порты одни и те же: use-case не различает их.
    for config in ({}, {"isolated_clone": True}):
        workspace = _build_workspace(cast("Mapping[str, object]", config))
        assert isinstance(workspace, Worktree)
        assert isinstance(workspace, PersistentWorkspace)


# --------------------------------------------------------------------------- #
# Оба композиционных вызова идут ЧЕРЕЗ переключатель (иначе флаг был бы мёртвым)
# --------------------------------------------------------------------------- #


def test_the_gated_assistant_lands_in_the_clone_when_the_flag_is_on(tmp_path: Path) -> None:
    # ``clone_root`` — в одноразовый каталог: с включённым флагом сборка материализует
    # окружение изоляции спавна (BOB-089.C), и писать его в рабочее дерево незачем.
    config = {"coder": {"enabled": True, "isolated_clone": True, "clone_root": str(tmp_path)}}
    assistant = _build_coding_assistant(config, **_coder_deps())  # type: ignore[arg-type]

    assert assistant is not None
    assert type(_workspace_of(assistant)) is GitClone


def test_the_gated_assistant_keeps_the_worktree_when_the_flag_is_off() -> None:
    config = {"coder": {"enabled": True, "isolated_clone": False}}
    assistant = _build_coding_assistant(config, **_coder_deps())  # type: ignore[arg-type]

    assert assistant is not None
    assert type(_workspace_of(assistant)) is GitWorktree


def test_the_interactive_manager_lands_in_the_clone_when_the_flag_is_on(
    tmp_path: Path,
) -> None:
    config = {
        "coder": {
            "interactive": True,
            "isolated_clone": True,
            "resume": True,
            "clone_root": str(tmp_path),
        }
    }
    manager = _build_interactive_session(config, **_interactive_deps())  # type: ignore[arg-type]

    assert manager is not None
    assert type(_workspace_of(manager)) is GitClone
    # Персистентный шов — ТОТ ЖЕ объект: одно рабочее место, два порта.
    assert manager._workspace is _workspace_of(manager)


def test_the_interactive_manager_keeps_the_worktree_when_the_flag_is_off() -> None:
    config = {"coder": {"interactive": True, "resume": True, "isolated_clone": False}}
    manager = _build_interactive_session(config, **_interactive_deps())  # type: ignore[arg-type]

    assert manager is not None
    assert type(_workspace_of(manager)) is GitWorktree
