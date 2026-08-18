# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Restart-notice adapter — объявление рестарта голосом Боба в личку owner'а и группу (BOB-094).

Реализует ``RestartNotifier`` use-case
:class:`~bob.proactivity.usecases.announce_restart.AnnounceRestart` над БОТОМ БОБА
(канон BOB-090.D: рестарт — это голос Боба, его бот, а не строка деплой-скрипта и не
системный нотис GUPPI). Две узкие двери:

* ``notify_owner`` — личка owner'а (``chat_id == owner_id``, без топика);
* ``notify_group`` — групповой чат в ТОПИКЕ Боба (``chat_id`` +
  ``message_thread_id == telegram.bob.topic_id``), чтобы объявление легло в тред Боба.

Транспорт только: одна plain-отправка каждой двери. Таймаут и best-effort-проглатывание
сбоя (чтобы shutdown не подвис) живут в use-case, а не здесь.
"""

from __future__ import annotations

from typing import Protocol


class _PlainNotifyBot(Protocol):
    """Минимальный send-шов: одна plain-реплика (тот же субсет, что у outage-нотиса).

    Interface-segregated субсет :class:`BotLike` — только ``send_message``, — так что
    любой ``BotLike`` удовлетворяет его структурно, а тест-фейк не обязан реализовывать
    весь протокол гейтвея.
    """

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object: ...


class _RestartNotifier:
    """Notifier рестарта: объявление в личку owner'а и в топик Боба через бот Боба (BOB-094)."""

    def __init__(
        self, *, bot: _PlainNotifyBot, owner_id: int, chat_id: int, topic_id: int | None
    ) -> None:
        self._bot = bot
        self._owner_id = owner_id
        self._chat_id = chat_id
        self._topic_id = topic_id

    async def notify_owner(self, text: str) -> None:
        """Отправить объявление в личку owner'а (без топика)."""
        await self._bot.send_message(chat_id=self._owner_id, text=text)

    async def notify_group(self, text: str) -> None:
        """Отправить объявление в групповой чат, в топик Боба."""
        await self._bot.send_message(
            chat_id=self._chat_id, text=text, message_thread_id=self._topic_id
        )
