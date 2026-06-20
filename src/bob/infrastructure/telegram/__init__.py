# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Telegram transport adapter (aiogram).

Long-polling intake with dedup, and a reply path (BOB-008, Variant A) that shows a
``sendChatAction("typing")`` indicator while it assembles the reply, then commits a
single **rich** message via ``send_rich_message`` (with a collapsible thinking block
and a silent plain ``send_message`` fallback). Markdown is turned into the typed
rich tree by :class:`MarkdownToRichMessage`. Native streaming is gone: Bob is reached
only through a group topic, where drafts are DM-only and edits are slow + flood-prone.
Transport only: no Higher-Mind / LLM / memory logic — it receives updates and
publishes :class:`MessageReceived` onto the EventBus, and delivers a reply given a
token async-iterator (consumed to assemble the full text, then sent once).
"""

from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import (
    PLAIN_TEXT_LIMIT,
    BotLike,
    TelegramGateway,
    UpdateLike,
)
from bob.infrastructure.telegram.guppi import GUPPI_REJECT_TEXT, GuppiHandler
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistration,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)
from bob.infrastructure.telegram.rich import (
    MarkdownToRichMessage,
    RichMessageSerializer,
)

__all__ = [
    "GUPPI_REJECT_TEXT",
    "MESSAGE_RECEIVED",
    "PLAIN_TEXT_LIMIT",
    "BotIdentity",
    "BotLike",
    "BotRegistration",
    "BotRegistry",
    "BotScope",
    "GuppiHandler",
    "MarkdownToRichMessage",
    "MessageReceived",
    "MultiBotGateway",
    "RichMessageSerializer",
    "TelegramGateway",
    "UpdateLike",
]
