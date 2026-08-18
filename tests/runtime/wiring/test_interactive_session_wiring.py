# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_interactive_session`` — the interactive-terminal wiring switch (BOB-083 .3).

The live, bidirectional ``claude`` terminal ships inert behind the ``coder.interactive``
flag (default off, mirroring ``coder.dev_dm`` / ``coder.nl_autostart``). This builder is
the ONE place the flag is read: off → ``None`` (the ``.4`` intake mode stays inert); on →
an :class:`InteractiveSessionManager` that reuses the isolated worktree + DM live-stream
and has NO PR-opener (it physically cannot merge / push main, INV-2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.interactive.usecases.session import InteractiveSessionManager
from bob.runtime.wiring.coding import (
    _build_interactive_session as _wire_build_interactive_session,
)
from tests.support.wiring_clone_root import with_a_throwaway_clone_root

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.social.usecases import Authorizer

# 🔴 Файлы окружения спавна — в ОДНОРАЗОВЫЙ каталог, а не в рабочее дерево (bob-c3r.1).
# С безопасной дорогой по умолчанию (клон + изоляция) сборка материализует их на КАЖДОМ
# вызове, а предмет этого файла другой; поэтому продакшн-строители здесь затенены обёрткой,
# подставляющей ``coder.clone_root``. Значение, заданное самим тестом, уважается как есть.


def _build_interactive_session(
    config: Mapping[str, object], **deps: object
) -> InteractiveSessionManager | None:
    """Как продакшн-строитель, но с одноразовым ``clone_root`` (см. комментарий выше)."""
    return _wire_build_interactive_session(
        with_a_throwaway_clone_root(config),
        **deps,  # type: ignore[arg-type]
    )


_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder — the manager is assembled, never sent through, during wiring."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 1, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": _bot(),
        "stream_bot": _bot(),
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def test_flag_off_yields_no_manager() -> None:
    assert _build_interactive_session({}, **_deps()) is None


def test_flag_off_explicit_false_yields_no_manager() -> None:
    config = {"coder": {"interactive": False}}
    assert _build_interactive_session(config, **_deps()) is None


def test_flag_on_builds_the_manager() -> None:
    config = {"coder": {"interactive": True}}
    manager = _build_interactive_session(config, **_deps())
    assert isinstance(manager, InteractiveSessionManager)
    # Built idle: no live session until an owner opens one (the ``.4`` intake mode drives it).
    assert manager.active() is False


def test_interactive_streamer_factory_builds_a_verbose_streamer() -> None:
    # BOB-085.2: the interactive DM output renders VERBOSE (full text + rich + chunked),
    # unlike the concise group one-way path — the factory bakes verbose=True in.
    config = {"coder": {"interactive": True}}
    manager = _build_interactive_session(config, **_deps())
    assert isinstance(manager, InteractiveSessionManager)
    streamer = manager._streamer_factory()
    assert isinstance(streamer, _DmLiveStreamer)
    assert streamer._verbose is True


def test_the_manager_can_tell_the_owner_the_session_ended_by_itself() -> None:
    # 🔴 bob-kv4: смерть процесса — единственная реплика, которую менеджер шлёт по
    # СОБСТВЕННОЙ инициативе (у неё нет хода-адресата). Без завязанного нотификатора
    # сеанс завершался бы честно, но МОЛЧА — а именно немоту эта беада и закрывает.
    config = {"coder": {"interactive": True}}
    manager = _build_interactive_session(config, **_deps())
    assert isinstance(manager, InteractiveSessionManager)
    assert isinstance(manager._notifier, _CodingOwnerNotifier)
    # Личка owner'а: 1:1 чат, никакого группового топика (INV-5 — группа не флудится).
    assert manager._notifier._chat_id == _OWNER_ID
    assert manager._notifier._topic_id is None


def test_the_ended_notice_stays_on_bobs_bot_even_when_the_firehose_is_guppis() -> None:
    # BOB-087.A1: механический поток идёт ЗА GUPPI, но это реплика САМОГО Боба (его
    # голос, session_voice) — она остаётся на ботe Боба, как строки режима интейка.
    config = {"coder": {"interactive": True, "stream_via_guppi": True}}
    deps = _deps()
    bob_bot, guppi_bot = _bot(), _bot()
    deps["bot"], deps["stream_bot"] = bob_bot, guppi_bot
    manager = _build_interactive_session(config, **deps)
    assert isinstance(manager, InteractiveSessionManager)
    assert isinstance(manager._notifier, _CodingOwnerNotifier)
    assert manager._notifier._sender._bot is bob_bot
