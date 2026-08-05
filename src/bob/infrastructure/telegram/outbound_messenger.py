# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:component=telegram

"""TelegramOutboundMessenger — транспорт отправки по точному адресу (BOB-090.B1).

Реализация :class:`~bob.capabilities.ports.OutboundMessenger` поверх УЖЕ существующего
:class:`~bob.infrastructure.telegram.gateway.RichMarkdownSender` — того самого шва, которым
Боб пишет owner-facing сообщения (rich, с падением в plain при ошибке разметки). Нового
транспорта в этом срезе не заводится: недоставало не канала, а понятия «исходящий адрес».

Тонкая по замыслу: адрес приходит аргументом каждого вызова (один отправитель обслуживает
любой чат и любой форум-топик), а ``topic_id`` передаётся как есть — в форум-группе
``None`` означает не «чат», а General, поэтому выдумывать тред нельзя. Все решения —
кому, куда и можно ли — приняты выше, в чистых ядрах; здесь только отправка. Сообщение
идёт ботом БОБА: в комнате появляется он, а не служебный голос.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.infrastructure.telegram.gateway import RichMarkdownSender

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike, MarkdownSendBot

__all__ = ["TelegramOutboundMessenger"]


class TelegramOutboundMessenger:
    """Отправить markdown в указанный чат/топик через бот Боба (rich, plain-фолбэк)."""

    def __init__(self, bot: BotLike) -> None:
        self._sender = RichMarkdownSender(cast("MarkdownSendBot", bot))

    async def send(self, *, chat_id: int, topic_id: int | None, markdown: str) -> None:
        """Отправить ``markdown`` в ``chat_id`` / ``topic_id`` (тред — как передали)."""
        await self._sender.send(
            chat_id=chat_id, markdown=markdown, message_thread_id=topic_id
        )
