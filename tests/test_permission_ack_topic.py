# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты треда у ack запроса разрешения (BOB-090.B5).

Симптом: в форум-группе лёгкое «спрошу Вову» приходило в General («main»), а не в топик
Боба — ``tell_requester`` слал без ``message_thread_id``, хотя ``notify_owner`` рядом слал
с ним. Проситель писал Бобу в его топике и получал ответ в другом месте.

Здесь проверяется, что ОБА канала нотиса уходят в топик Боба (и что в личке, где топика
нет, тред остаётся ``None`` — приватный чат форум-топиков не имеет).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from bob.social.adapters.permission_channels import _PermissionNotifier

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32


@dataclass
class _FakeMessage:
    message_id: int = 1


@dataclass
class _RichCall:
    chat_id: int
    message_thread_id: int | None


@dataclass
class _FakeBot:
    rich_calls: list[_RichCall] = field(default_factory=list)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        del text
        self.rich_calls.append(_RichCall(chat_id, message_thread_id))
        return _FakeMessage()

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        del rich_message
        self.rich_calls.append(_RichCall(chat_id, message_thread_id))
        return _FakeMessage()


@pytest.mark.asyncio
async def test_requester_ack_lands_in_bobs_topic_not_general() -> None:
    # BOB-090.B5: ack просителю уходит в ТОТ ЖЕ топик, где Боб разговаривает, а не в General.
    bot = _FakeBot()
    notifier = _PermissionNotifier(
        bot=cast("BotLike", bot), chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID
    )

    await notifier.tell_requester("Спрошу Вову.")

    assert len(bot.rich_calls) == 1
    assert bot.rich_calls[0].chat_id == _CHAT_ID
    assert bot.rich_calls[0].message_thread_id == _BOB_TOPIC_ID


@pytest.mark.asyncio
async def test_both_permission_channels_share_the_same_thread() -> None:
    # Нотис owner'у и ack просителю — один разговор в одном треде: расхождение и было дефектом.
    bot = _FakeBot()
    notifier = _PermissionNotifier(
        bot=cast("BotLike", bot), chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID
    )

    await notifier.notify_owner("Вова, Норман просит…")
    await notifier.tell_requester("Спрошу Вову.")

    threads = [call.message_thread_id for call in bot.rich_calls]
    assert threads == [_BOB_TOPIC_ID, _BOB_TOPIC_ID]


@pytest.mark.asyncio
async def test_ack_without_a_topic_stays_unthreaded() -> None:
    # Личка форум-топиков не имеет: без настроенного топика тред остаётся None (не выдуман).
    bot = _FakeBot()
    notifier = _PermissionNotifier(bot=cast("BotLike", bot), chat_id=_CHAT_ID, topic_id=None)

    await notifier.tell_requester("Спрошу Вову.")

    assert bot.rich_calls[0].message_thread_id is None
