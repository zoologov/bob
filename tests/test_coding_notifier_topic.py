# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты вывода coding-сессии в топик Боба (BOB-042 Fix B).

Owner ставит задачу Бобу в своём топике (NL-путь BOB-041), значит и ответы сессии
(план / нарратив / PR) должны падать в тот же тред, не в General. Поэтому
``_CodingOwnerNotifier`` использует ``message_thread_id == telegram.bob.topic_id`` и
сохраняет rich/markdown-путь (BOB-041 .1) плюс plain-фолбэк. Отправитель — бот Боба
(BOB-046 .1); здесь проверяется топик/markdown-путь (отправитель — в
``test_coding_sender_is_bob``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from bob.app import _CodingOwnerNotifier

if TYPE_CHECKING:
    from aiogram.types import InputRichMessage

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 42


@dataclass
class _FakeMessage:
    message_id: int = 1
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _RichCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _PlainCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    rich_raises: bool = False
    rich_calls: list[_RichCall] = field(default_factory=list)
    plain_calls: list[_PlainCall] = field(default_factory=list)

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.rich_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich rejected",
            )
        self.rich_calls.append(
            _RichCall(chat_id, rich_message.markdown, message_thread_id)
        )
        return _FakeMessage()

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.plain_calls.append(_PlainCall(chat_id, text, message_thread_id))
        return _FakeMessage()


@pytest.mark.asyncio
async def test_notifier_sends_coding_message_to_bobs_topic() -> None:
    # Fix B: coding messages land in Bob's TOPIC (message_thread_id == bob topic_id),
    # not General (None) — the owner sees Bob's session replies in the same thread.
    bot = _FakeBot()
    notifier = _CodingOwnerNotifier(
        bot=bot, chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID
    )

    await notifier.send("## План\n\n**правка** и `код`")

    assert len(bot.rich_calls) == 1  # the rich/markdown path is still used
    assert bot.rich_calls[0].chat_id == _CHAT_ID
    assert bot.rich_calls[0].message_thread_id == _BOB_TOPIC_ID  # NOT None
    assert bot.plain_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_id", [_BOB_TOPIC_ID, None])
async def test_notifier_threads_into_the_configured_topic(topic_id: int | None) -> None:
    # The notifier faithfully threads into whatever topic it is configured with: Bob's
    # topic when set (Fix B), or General (None) when no topic is configured — the rich
    # markdown path is used either way. This pins the General fallback branch too.
    bot = _FakeBot()
    notifier = _CodingOwnerNotifier(bot=bot, chat_id=_CHAT_ID, topic_id=topic_id)

    await notifier.send("## План")

    assert len(bot.rich_calls) == 1
    assert bot.rich_calls[0].chat_id == _CHAT_ID
    assert bot.rich_calls[0].message_thread_id == topic_id
    assert bot.plain_calls == []


@pytest.mark.asyncio
async def test_notifier_plain_fallback_keeps_bobs_topic() -> None:
    # On a rich failure the plain fallback must still target Bob's topic (never General).
    bot = _FakeBot(rich_raises=True)
    notifier = _CodingOwnerNotifier(
        bot=bot, chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID
    )

    await notifier.send("## План")

    assert bot.rich_calls == []
    assert len(bot.plain_calls) == 1
    assert bot.plain_calls[0].message_thread_id == _BOB_TOPIC_ID
