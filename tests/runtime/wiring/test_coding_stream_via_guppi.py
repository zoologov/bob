# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``coder.stream_via_guppi`` wiring switch — firehose bot selection (BOB-087.A1).

Canon: GUPPI is the dry executor, Bob is the mind. The mechanical coder/interactive firehose
(per-event ``narrate`` + the DM live-stream) may be sent AS GUPPI (through GUPPI's bot) while
Bob's own voice (the session-voice gate lines, reactions) stays on BOB'S bot. This builder is
the ONE place the flag is read: OFF (default) → the firehose stays on Bob's bot exactly as
before (``stream_notifier`` is ``None`` → the use-case falls back to the Bob channel); ON →
the firehose ``stream_notifier`` + the DM live-streamer are built over the GUPPI bot, and the
main ``notifier`` (Bob's gate lines) stays on Bob's bot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.runtime.wiring.coding import _build_coding_assistant as _wire_build_coding_assistant
from bob.runtime.wiring.coding import (
    _build_interactive_session as _wire_build_interactive_session,
)
from tests.support.wiring_clone_root import with_a_throwaway_clone_root

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.coding.usecases.coding_assistant import CodingAssistant, WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.interactive.usecases.session import InteractiveSessionManager
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.memory.self_action import SelfAction
    from bob.social.usecases import Authorizer

# 🔴 Файлы окружения спавна — в ОДНОРАЗОВЫЙ каталог, а не в рабочее дерево (bob-c3r.1).
# С безопасной дорогой по умолчанию (клон + изоляция) сборка материализует их на КАЖДОМ
# вызове, а предмет этого файла другой; поэтому продакшн-строители здесь затенены обёрткой,
# подставляющей ``coder.clone_root``. Значение, заданное самим тестом, уважается как есть.


def _build_coding_assistant(
    config: Mapping[str, object], **deps: object
) -> CodingAssistant | None:
    """Как продакшн-строитель, но с одноразовым ``clone_root`` (см. комментарий выше)."""
    return _wire_build_coding_assistant(
        with_a_throwaway_clone_root(config),
        **deps,  # type: ignore[arg-type]
    )


def _build_interactive_session(
    config: Mapping[str, object], **deps: object
) -> InteractiveSessionManager | None:
    """Как продакшн-строитель, но с одноразовым ``clone_root`` (см. комментарий выше)."""
    return _wire_build_interactive_session(
        with_a_throwaway_clone_root(config),
        **deps,  # type: ignore[arg-type]
    )


_OWNER_ID = 27468732
_CHAT_ID = -100123
_TOPIC_ID = 42


class _BobBot:
    """Bob's bot placeholder — assembled into notifiers, never sent through, at wiring."""


class _GuppiBot:
    """GUPPI's bot placeholder — the firehose target when the flag is ON."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


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


def _bob() -> BotLike:
    return cast("BotLike", _BobBot())


def _guppi() -> BotLike:
    return cast("BotLike", _GuppiBot())


def _assistant_deps(bob: BotLike, guppi: BotLike) -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "notifier_bot": bob,
        "stream_bot": guppi,
        "chat_id": _CHAT_ID,
        "topic_id": _TOPIC_ID,
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
        "recorder": cast("SelfActionRecorder", _StubRecorder()),
        "work_journal": cast("WorkJournalRecorder", _StubWorkJournal()),
    }


def _notifier_bot(notifier: object) -> object:
    assert isinstance(notifier, _CodingOwnerNotifier)
    return notifier._sender._bot


def test_flag_off_firehose_stays_on_bob_bot() -> None:
    config = {"coder": {"enabled": True}}
    bob, guppi = _bob(), _guppi()
    assistant = _build_coding_assistant(config, **_assistant_deps(bob, guppi))
    assert assistant is not None
    # Bob's gate-line notifier is Bob's bot; the firehose falls back to the SAME channel.
    assert _notifier_bot(assistant._notifier) is bob
    assert assistant._stream_notifier is assistant._notifier


def test_flag_on_firehose_goes_to_guppi_voice_stays_bob() -> None:
    config = {"coder": {"enabled": True, "stream_via_guppi": True}}
    bob, guppi = _bob(), _guppi()
    assistant = _build_coding_assistant(config, **_assistant_deps(bob, guppi))
    assert assistant is not None
    # Bob's voice (gate lines) still through Bob's bot…
    assert _notifier_bot(assistant._notifier) is bob
    # …but the mechanical firehose stream_notifier is a DISTINCT channel over GUPPI's bot.
    assert assistant._stream_notifier is not assistant._notifier
    assert _notifier_bot(assistant._stream_notifier) is guppi


def test_flag_on_dm_live_streamer_targets_guppi_bot() -> None:
    config = {"coder": {"enabled": True, "stream_via_guppi": True, "dev_dm": True}}
    bob, guppi = _bob(), _guppi()
    assistant = _build_coding_assistant(config, **_assistant_deps(bob, guppi))
    assert assistant is not None
    streamer = assistant._live_streamer
    assert isinstance(streamer, _DmLiveStreamer)
    assert _notifier_bot(streamer._notifier) is guppi


def test_flag_off_dm_live_streamer_stays_on_bob_bot() -> None:
    config = {"coder": {"enabled": True, "dev_dm": True}}
    bob, guppi = _bob(), _guppi()
    assistant = _build_coding_assistant(config, **_assistant_deps(bob, guppi))
    assert assistant is not None
    streamer = assistant._live_streamer
    assert isinstance(streamer, _DmLiveStreamer)
    assert _notifier_bot(streamer._notifier) is bob


def _session_deps(bob: BotLike, guppi: BotLike) -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": bob,
        "stream_bot": guppi,
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def test_interactive_streamer_firehose_follows_the_flag() -> None:
    on = {"coder": {"interactive": True, "stream_via_guppi": True}}
    off = {"coder": {"interactive": True}}
    bob, guppi = _bob(), _guppi()

    manager_on = _build_interactive_session(on, **_session_deps(bob, guppi))
    manager_off = _build_interactive_session(off, **_session_deps(bob, guppi))
    assert manager_on is not None
    assert manager_off is not None
    streamer_on = manager_on._streamer_factory()
    streamer_off = manager_off._streamer_factory()
    assert isinstance(streamer_on, _DmLiveStreamer)
    assert isinstance(streamer_off, _DmLiveStreamer)
    # ON → the interactive DM firehose renders through GUPPI's bot; OFF → Bob's bot.
    assert _notifier_bot(streamer_on._notifier) is guppi
    assert _notifier_bot(streamer_off._notifier) is bob
