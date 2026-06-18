# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Telegram transport adapter (python-telegram-bot).

Long-polling intake with dedup, and streaming replies via batched, throttled
``editMessageText``. Transport only: no Higher-Mind / LLM / memory logic — it
receives updates and publishes :class:`MessageReceived` onto the EventBus, and
streams out a reply given a token async-iterator.
"""

from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import BotLike, TelegramGateway, UpdateLike

__all__ = [
    "MESSAGE_RECEIVED",
    "BotLike",
    "MessageReceived",
    "TelegramGateway",
    "UpdateLike",
]
