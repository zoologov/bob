# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Telegram-адаптеры индикатора работы coding-сессии (BOB-046 .2).

Два дополняющих индикатора для coding-сессии, реализующих сеймы use-case
(:class:`~bob.coding.usecases.coding_assistant.TypingKeepalive` /
:class:`~bob.coding.usecases.coding_assistant.StatusPanel`) поверх бота Боба:

* :class:`TypingKeepalive` — «Боб печатает…» на время немых claude-пауз. Реюз идиомы
  BOB-009 ``typing_indicator``: на вход — один ``sendChatAction("typing")`` в топик Боба,
  затем фоновая задача рефрешит его каждые ``interval`` секунд (5-секундный typing не
  истекает в минутной паузе); на выход — задача снимается и ожидается (без утечки). Любой
  сбой action'а логируется и глотается — индикатор НИКОГДА не валит сессию.
* :class:`StatusPanel` — одно editable сообщение-статус. ``open`` шлёт строку раз и
  запоминает её ``message_id``; ``update`` РЕДАКТИРУЕТ то же сообщение (``editMessageText``)
  — не спам. Если редактировать нечем (нет id / ``edit_message_text`` сбоит) — деградирует
  в no-op (current behavior: без статус-строки), не падая.

Всё инъектируется (бот + clock/sleep-сеймы), поэтому адаптеры детерминированы в тестах и
не трогают настоящий Telegram.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from bob.infrastructure.telegram.gateway import MessageLike

logger = logging.getLogger(__name__)

__all__ = ["EditableStatusBot", "StatusPanel", "TypingActionBot", "TypingKeepalive"]

# The Telegram chat action used for the "Bob is typing…" indicator.
_TYPING_ACTION = "typing"


class TypingActionBot(Protocol):
    """Узкая поверхность бота для typing-индикатора (только ``send_chat_action``)."""

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool: ...


class EditableStatusBot(Protocol):
    """Узкая поверхность бота для статус-панели: послать одно сообщение и редактировать его."""

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike: ...

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> object: ...


class TypingKeepalive:
    """«Боб печатает…» на время долгих claude-пауз (реюз идиомы BOB-009).

    Ноль-арг фабрика async-контекст-менеджера, который use-case оборачивает вокруг
    plan/execute-прогонов: на enter — один typing-action в топик Боба + фоновый рефреш
    каждые ``interval`` секунд (инъектированный ``sleep`` задаёт ритм — детерминизм в
    тестах), на exit — задача снимается и ожидается. Сбой action'а глотается.
    """

    def __init__(
        self,
        *,
        bot: TypingActionBot,
        chat_id: int,
        thread_id: int | None,
        interval: float,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._interval = interval
        self._sleep = sleep

    @contextlib.asynccontextmanager
    async def __call__(self) -> AsyncIterator[None]:
        """Keep the typing action alive for the duration of the wrapped run."""
        await self._send_typing()
        task = asyncio.create_task(self._keepalive())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _keepalive(self) -> None:
        """Re-send the typing action every ``interval`` seconds until cancelled."""
        while True:
            await self._sleep(self._interval)
            await self._send_typing()

    async def _send_typing(self) -> None:
        """Send one ``sendChatAction("typing")`` into Bob's topic (best-effort)."""
        try:
            await self._bot.send_chat_action(
                chat_id=self._chat_id,
                action=_TYPING_ACTION,
                message_thread_id=self._thread_id,
            )
        except Exception as exc:  # an indicator must never break the session
            logger.info("coding typing action failed (ignored): %s", exc)


class StatusPanel:
    """One editable status message edited through the session phases (BOB-046 .2).

    ``open`` шлёт строку один раз и запоминает её ``message_id`` (в топике Боба); ``update``
    редактирует то же сообщение через ``edit_message_text`` — одно сообщение, не спам. Нет
    запомненного id (``open`` не прошёл / не звался) или сбой редактирования → no-op
    (деградация в current behavior без статус-строки, без падения сессии).
    """

    def __init__(
        self, *, bot: EditableStatusBot, chat_id: int, thread_id: int | None
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._thread_id = thread_id
        self._message_id: int | None = None

    async def open(self, text: str) -> None:
        """Send the status message once and remember its id (best-effort)."""
        self._message_id = None
        try:
            message = await self._bot.send_message(
                chat_id=self._chat_id, text=text, message_thread_id=self._thread_id
            )
        except Exception as exc:  # no status panel rather than a broken session
            logger.info("coding status open failed (ignored): %s", exc)
            return
        self._message_id = message.message_id

    async def update(self, text: str) -> None:
        """Edit the same status message to ``text`` (no-op when there is nothing to edit)."""
        if self._message_id is None:
            return
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id, message_id=self._message_id, text=text
            )
        except Exception as exc:  # a stale/edit error must never break the session
            logger.info("coding status update failed (ignored): %s", exc)
