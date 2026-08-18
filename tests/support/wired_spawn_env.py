# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Окружение, которое ПРОДАКШН-ПРОВОДКА отдаёт спавну ``claude`` — оба рантайма.

ОДНА ответственность: собрать по форме конфига настоящие ``_build_coding_assistant`` +
``_build_interactive_session`` и достать из них тот самый ``env``, который уедет в
``create_subprocess_exec``. Ни одного решения тут нет — только доступ к границе процесса.

Живёт в ``tests/support``, потому что этот доступ нужен ДВУМ разным уровням проверки, и
второй копии у него быть не должно: проводочный тест (``tests/runtime/wiring``) читает
состав окружения, а real-git тест (``tests/infrastructure/coding``) проверяет, что с этим
окружением НАСТОЯЩИЙ git отказывается пушить. Разъедься копии — и «барьер стоит» осталось
бы доказанным на одном уровне и опровергнутым на другом.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.claude_runner import SubprocessClaudeRunner, _ExecStreamRunner
from bob.interactive.adapters.runner import (
    InteractiveClaudeRunner,
    _ExecInteractiveSpawner,
)
from bob.runtime.wiring.coding import _build_coding_assistant, _build_interactive_session

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.memory.self_action import SelfAction
    from bob.social.usecases import Authorizer

__all__ = ["OWNER_ID", "wired_spawn_envs"]

OWNER_ID = 27468732
_CHAT_ID = -100123


class _StubBot:
    """Заглушка бота — собирается в нотификаторы, но на проводке не отправляет ничего."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 15, tzinfo=UTC)


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


def wired_spawn_envs(config: Mapping[str, object]) -> list[dict[str, str] | None]:
    """Окружение, которое каждый из двух рантаймов передаст спавну ``claude``.

    Порядок фиксирован: ``[одноразовый кодер, живой терминал]``. ``None`` означает «спавн
    вообще без ``env=``», то есть унаследованное окружение процесса Боба.
    """
    assistant = _build_coding_assistant(
        config,
        repo=cast("SqliteConnection", _StubConnection()),
        authorizer=cast("Authorizer", _StubAuthorizer()),
        notifier_bot=_bot(),
        stream_bot=_bot(),
        chat_id=_CHAT_ID,
        topic_id=None,
        owner_id=OWNER_ID,
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
        owner_id=OWNER_ID,
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
