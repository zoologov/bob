# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Owner-alert adapter — сигнал владельцу о простое LLM-провайдера ботом Боба (BOB-116 D4).

Реализует порт :class:`~bob.kernel.ports.OwnerAlertSink` над БОТОМ БОБА: одна plain-отправка
в личку владельца (``chat_id == owner_id``, без топика), текст байт-в-байт. Текст собирает
монитор здоровья по шаблону, без LLM; этот путь обязан работать именно тогда, когда сломан
модельный стек, поэтому модуль не зависит ни от провайдеров, ни от роутера.

Отправка идёт под таймаутом (как у объявления рестарта), чтобы зависший транспорт не держал
монитор. Ошибка и таймаут уходят наружу: решение «проглотить с warning» принадлежит монитору.
От :mod:`~bob.infrastructure.telegram.restart_notifier` отличается смыслом (простой, а не
рестарт) и тем, что таймаут живёт в самом адаптере, а не в use-case.

:class:`NoopOwnerAlert` — порт для ``llm.health.owner_alert: false``: сигнал выключен.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

#: Таймаут одной отправки, секунд: тот же, что у объявления рестарта (BOB-094).
DEFAULT_TIMEOUT_SECONDS = 5.0


class _PlainNotifyBot(Protocol):
    """Минимальный send-шов: одна plain-реплика.

    Interface-segregated субсет :class:`BotLike` — только ``send_message``, — так что любой
    ``BotLike`` удовлетворяет его структурно, а тест-фейк не реализует весь протокол гейтвея.
    """

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object: ...


class OwnerAlert:
    """Сигнал владельцу в личку через бот Боба, под таймаутом (BOB-116)."""

    def __init__(
        self,
        bot: _PlainNotifyBot,
        owner_id: int,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {timeout_seconds}"
            raise ValueError(msg)
        self._bot = bot
        self._owner_id = owner_id
        self._timeout = timeout_seconds

    @property
    def timeout_seconds(self) -> float:
        """Таймаут одной отправки, секунд."""
        return self._timeout

    async def notify_owner(self, text: str) -> None:
        """Отправить ``text`` в личку владельца; ``TimeoutError`` и ошибки транспорта — наружу."""
        await asyncio.wait_for(
            self._bot.send_message(chat_id=self._owner_id, text=text),
            timeout=self._timeout,
        )


class NoopOwnerAlert:
    """Выключенный сигнал владельцу (``llm.health.owner_alert: false``): ничего не шлёт."""

    async def notify_owner(self, text: str) -> None:
        """Ничего не делать."""
