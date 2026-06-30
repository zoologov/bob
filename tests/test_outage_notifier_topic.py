# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты GUPPI-нотиса об отказе в топик Боба (BOB-049 .3).

Принцип «полный Боб или честный GUPPI-нотис»: при стойком сбое essential-шага GUPPI
честно сообщает о недоступности Боба в ЕГО топик системным голосом — не деградированный
полу-ответ. Здесь проверяется, что ``_GuppiOutageNotifier`` шлёт фиксированный системный
текст в ``message_thread_id == telegram.bob.topic_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from bob.app import _GuppiOutageNotifier
from bob.infrastructure.telegram.guppi import GUPPI_OUTAGE_TEXT

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 42


@dataclass
class _FakeMessage:
    message_id: int = 1


@dataclass
class _PlainCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    plain_calls: list[_PlainCall] = field(default_factory=list)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.plain_calls.append(_PlainCall(chat_id, text, message_thread_id))
        return _FakeMessage()


@pytest.mark.asyncio
async def test_outage_notice_lands_in_bobs_topic_as_a_system_line() -> None:
    # BOB-049 .3: the honest GUPPI outage notice is posted into Bob's TOPIC (not General),
    # carrying the fixed third-person system text — clearly GUPPI reporting, not Bob.
    bot = _FakeBot()
    notifier = _GuppiOutageNotifier(bot=bot, chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID)

    await notifier.notify_outage()

    assert len(bot.plain_calls) == 1
    call = bot.plain_calls[0]
    assert call.chat_id == _CHAT_ID
    assert call.message_thread_id == _BOB_TOPIC_ID  # Bob's topic, NOT General (None)
    assert call.text == GUPPI_OUTAGE_TEXT
    assert "Боб временно недоступен" in call.text  # honest outage, not a Bob reply
