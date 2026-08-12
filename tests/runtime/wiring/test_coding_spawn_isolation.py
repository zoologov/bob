# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты проводки изоляции окружения спавна (BOB-089, срез C).

Доезжает ли решение «спавн не видит кредов owner'а» до ГРАНИЦЫ ПРОЦЕССА — то есть до того
``env``, который оба рабочих рантайма (одноразовый кодер и живой терминал) передают
``claude``. Читается тот же флаг, что выбирает рабочее место (``coder.isolated_clone``): у
клона свой ``.git``, и изоляция кредов — вторая половина той же гарантии, поэтому отдельного
флага у неё нет.

🔴 OFF-путь: ``None``, то есть спавн вообще без ``env=`` и без единого файла на диске.

🔴 Кредов спавну НЕ выдаётся даже при включённом флаге: ветку в форк пушит процесс САМОГО
Боба (``GitClone.commit_and_push``), а не ``claude`` внутри клона. Стор кредов появляется
только там, где токен передан явно — сейчас такого вызывающего в проде нет, и это записано
честно, а не выдано за готовую фичу.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.claude_runner import SubprocessClaudeRunner, _ExecStreamRunner
from bob.coding.push_guard import PUSH_GUARD_STUB_URL
from bob.interactive.adapters.runner import (
    InteractiveClaudeRunner,
    _ExecInteractiveSpawner,
)
from bob.runtime.wiring.coding import _build_coding_assistant, _build_interactive_session

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.memory.self_action import SelfAction
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732
_CHAT_ID = -100123


class _StubBot:
    """Заглушка бота — собирается в нотификаторы, но на проводке не отправляет ничего."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 6, tzinfo=UTC)


class _StubConnection:
    """Заглушка соединения — стор её держит, но на проводке не трогает."""


class _StubRecorder:
    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        return None


class _StubWorkJournal:
    async def record_session(
        self,
        task: str,
        facts: object,
        outcome: object,
        *,
        sender_id: int | None = None,
    ) -> None:
        return None


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _spawn_envs(config: Mapping[str, object]) -> list[dict[str, str] | None]:
    """Окружение, которое каждый из двух рантаймов передаст спавну ``claude``."""
    assistant = _build_coding_assistant(
        config,
        repo=cast("SqliteConnection", _StubConnection()),
        authorizer=cast("Authorizer", _StubAuthorizer()),
        notifier_bot=_bot(),
        stream_bot=_bot(),
        chat_id=_CHAT_ID,
        topic_id=None,
        owner_id=_OWNER_ID,
        clock=cast("Clock", _StubClock()),
        recorder=cast("SelfActionRecorder", _StubRecorder()),
        work_journal=cast("WorkJournalRecorder", _StubWorkJournal()),
    )
    manager = _build_interactive_session(
        config,
        repo=cast("SqliteConnection", _StubConnection()),
        authorizer=cast("Authorizer", _StubAuthorizer()),
        bot=_bot(),
        stream_bot=_bot(),
        owner_id=_OWNER_ID,
        clock=cast("Clock", _StubClock()),
    )
    assert assistant is not None
    assert manager is not None
    one_shot = assistant._runner
    assert isinstance(one_shot, SubprocessClaudeRunner)
    boundary = one_shot._runner
    assert isinstance(boundary, _ExecStreamRunner)
    live = manager._runner_factory()
    assert isinstance(live, InteractiveClaudeRunner)
    spawner = live._spawner
    assert isinstance(spawner, _ExecInteractiveSpawner)
    return [boundary._env, spawner._env]


def _config(tmp_path: Path, **coder: object) -> dict[str, object]:
    return {
        "coder": {
            "enabled": True,
            "interactive": True,
            "clone_root": str(tmp_path / "clones"),
            **coder,
        }
    }


# --------------------------------------------------------------------------- #
# OFF-путь: ни окружения, ни файлов
# --------------------------------------------------------------------------- #


def test_the_default_wiring_overrides_no_environment_and_writes_nothing(
    tmp_path: Path,
) -> None:
    assert _spawn_envs(_config(tmp_path)) == [None, None]
    assert not (tmp_path / "clones").exists()


def test_an_explicit_off_flag_stays_inert(tmp_path: Path) -> None:
    assert _spawn_envs(_config(tmp_path, isolated_clone=False)) == [None, None]


# --------------------------------------------------------------------------- #
# ON-путь: обе границы процесса получают одну и ту же изоляцию
# --------------------------------------------------------------------------- #


def test_the_isolated_clone_flag_isolates_both_spawns_from_the_owners_credentials(
    tmp_path: Path,
) -> None:
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True))

    for env in envs:
        assert env is not None
        assert env["GIT_CONFIG_GLOBAL"].startswith(str(tmp_path / "clones"))
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_ASKPASS"].startswith(str(tmp_path / "clones"))
        assert env["GH_CONFIG_DIR"].startswith(str(tmp_path / "clones"))
        pairs = [
            (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        ]
        assert ("credential.helper", "") in pairs


def test_both_runtimes_get_one_and_the_same_isolation(tmp_path: Path) -> None:
    # Одно решение на загрузку: разойдись они — и «изолирован» был бы только один рантайм.
    one_shot, live = _spawn_envs(_config(tmp_path, isolated_clone=True))
    assert one_shot is not None
    assert live is not None
    assert one_shot["GIT_CONFIG_GLOBAL"] == live["GIT_CONFIG_GLOBAL"]


def test_the_spawn_gets_no_credential_store_because_bob_pushes_himself(
    tmp_path: Path,
) -> None:
    # 🔴 Никаких кредов спавну: ветку в форк пушит процесс Боба, а не claude в клоне.
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True))

    for env in envs:
        assert env is not None
        assert not any("store --file=" in value for value in env.values())
    assert not (tmp_path / "clones" / ".spawn-env" / "credentials").exists()


def test_the_controlled_environment_is_materialised_on_disk(tmp_path: Path) -> None:
    _spawn_envs(_config(tmp_path, isolated_clone=True))

    root = tmp_path / "clones" / ".spawn-env"
    assert (root / "gitconfig").is_file()
    assert (root / "gh").is_dir()
    # «В никуда» — значит этого файла нет.
    assert not (root / "askpass-disabled").exists()


def test_the_isolation_lives_beside_the_clones_never_inside_one(tmp_path: Path) -> None:
    # Каталог рабочего места — ``<clone_root>/<slug ветки>``; точка в начале имени в
    # ``bob/<slug>``-ветке невыразима, поэтому столкновения имён не бывает.
    _spawn_envs(_config(tmp_path, isolated_clone=True))

    assert [item.name for item in (tmp_path / "clones").iterdir()] == [".spawn-env"]


# --------------------------------------------------------------------------- #
# Два слоя: барьер push'а остаётся вторым, а не заменяется
# --------------------------------------------------------------------------- #


def test_the_push_barrier_and_the_isolation_reach_the_spawn_together(
    tmp_path: Path,
) -> None:
    envs = _spawn_envs(_config(tmp_path, isolated_clone=True, allow_bypass=True))

    for env in envs:
        assert env is not None
        values = [env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))]
        assert any(PUSH_GUARD_STUB_URL in value for value in values)
        assert "credential.helper" in values
