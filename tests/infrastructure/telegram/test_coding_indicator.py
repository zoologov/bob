# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты Telegram-адаптеров индикатора работы coding-сессии (BOB-046 .2).

Покрыто:
* TypingKeepalive: один typing-action на enter, рефреш по injected ``sleep``, снятие
  задачи на exit (без утечки); сбой action'а проглочен;
* StatusPanel: ``open`` шлёт один раз и запоминает id, ``update`` РЕДАКТИРУЕТ то же
  сообщение (editMessageText); нет id / сбой редактирования → no-op без падения.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from bob.infrastructure.telegram.coding_indicator import StatusPanel, TypingKeepalive

_CHAT_ID = 100
_THREAD_ID = 7


@dataclass
class _Message:
    message_id: int
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _FakeBot:
    """Records the indicator's Telegram calls; can be told to fail a given call."""

    actions: list[tuple[int, str, int | None]] = field(default_factory=list)
    sent: list[tuple[int, str, int | None]] = field(default_factory=list)
    edits: list[tuple[int, int, str]] = field(default_factory=list)
    next_message_id: int = 555
    fail_action: bool = False
    fail_send: bool = False
    fail_edit: bool = False

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        if self.fail_action:
            raise RuntimeError("action boom")
        self.actions.append((chat_id, action, message_thread_id))
        return True

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _Message:
        if self.fail_send:
            raise RuntimeError("send boom")
        self.sent.append((chat_id, text, message_thread_id))
        return _Message(
            message_id=self.next_message_id, text=text, message_thread_id=message_thread_id
        )

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> object:
        if self.fail_edit:
            raise RuntimeError("edit boom")
        self.edits.append((chat_id, message_id, text))
        return _Message(message_id=message_id, text=text)


@pytest.mark.asyncio
async def test_typing_fires_on_enter_and_refreshes_then_stops() -> None:
    bot = _FakeBot()
    refreshed = asyncio.Event()

    async def _sleep(seconds: float) -> None:
        # First wait → fire a refresh; then block so the keepalive does not busy-loop.
        if not refreshed.is_set():
            refreshed.set()
            return
        await asyncio.Event().wait()

    keepalive = TypingKeepalive(
        bot=bot, chat_id=_CHAT_ID, thread_id=_THREAD_ID, interval=4.0, sleep=_sleep
    )

    async with keepalive():
        # The enter action lands immediately; the refresh fires via the injected sleep.
        await asyncio.wait_for(refreshed.wait(), timeout=1.0)
        await asyncio.sleep(0)  # let the keepalive task send the refresh

    # At least the enter action + one refresh, all into Bob's topic; task is cancelled
    # on exit (no leak — the test returns).
    assert len(bot.actions) >= 2
    assert all(a == (_CHAT_ID, "typing", _THREAD_ID) for a in bot.actions)


@pytest.mark.asyncio
async def test_typing_action_failure_is_swallowed() -> None:
    bot = _FakeBot(fail_action=True)

    async def _sleep(seconds: float) -> None:
        await asyncio.Event().wait()

    keepalive = TypingKeepalive(
        bot=bot, chat_id=_CHAT_ID, thread_id=None, interval=4.0, sleep=_sleep
    )

    # A failing typing action must never break the wrapped run.
    async with keepalive():
        pass

    assert bot.actions == []


@pytest.mark.asyncio
async def test_status_panel_opens_once_and_edits_in_place() -> None:
    bot = _FakeBot(next_message_id=42)
    panel = StatusPanel(bot=bot, chat_id=_CHAT_ID, thread_id=_THREAD_ID)

    await panel.open("⏳ план")
    await panel.update("⚙️ выполняю")
    await panel.update("✅ PR")

    # ONE send, then edits of THAT message id — never a second send.
    assert bot.sent == [(_CHAT_ID, "⏳ план", _THREAD_ID)]
    assert bot.edits == [(_CHAT_ID, 42, "⚙️ выполняю"), (_CHAT_ID, 42, "✅ PR")]


@pytest.mark.asyncio
async def test_status_panel_update_without_open_is_noop() -> None:
    bot = _FakeBot()
    panel = StatusPanel(bot=bot, chat_id=_CHAT_ID, thread_id=_THREAD_ID)

    await panel.update("⚙️ выполняю")  # never opened → nothing to edit

    assert bot.edits == []


@pytest.mark.asyncio
async def test_status_panel_open_failure_degrades_to_no_panel() -> None:
    bot = _FakeBot(fail_send=True)
    panel = StatusPanel(bot=bot, chat_id=_CHAT_ID, thread_id=_THREAD_ID)

    await panel.open("⏳ план")  # send fails → no id stored
    await panel.update("⚙️ выполняю")  # nothing to edit → no-op

    assert bot.sent == []
    assert bot.edits == []


@pytest.mark.asyncio
async def test_status_panel_edit_failure_is_swallowed() -> None:
    bot = _FakeBot(next_message_id=9, fail_edit=True)
    panel = StatusPanel(bot=bot, chat_id=_CHAT_ID, thread_id=_THREAD_ID)

    await panel.open("⏳ план")
    await panel.update("⚙️ выполняю")  # edit raises → swallowed, session unaffected

    assert bot.sent == [(_CHAT_ID, "⏳ план", _THREAD_ID)]
    assert bot.edits == []
