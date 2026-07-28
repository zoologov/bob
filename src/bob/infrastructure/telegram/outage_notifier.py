# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""GUPPI outage-notice adapter — the honest "Bob unavailable" system line (BOB-049 .3).

Realises HandleMessage's ``OutageNotifier`` seam over BOB'S bot: when an ESSENTIAL turn
step keeps failing after the bounded retries, GUPPI (the infrastructure subsystem)
honestly reports the outage into Bob's topic instead of shipping a degraded half-answer.
Extracted verbatim from the composition root (BOB-062.7a).
"""

from __future__ import annotations

from typing import Protocol

from bob.infrastructure.telegram.guppi import GUPPI_OUTAGE_TEXT


class _PlainNotifyBot(Protocol):
    """The minimal send surface the outage notifier needs: one plain message (BOB-049 .3).

    Interface-segregated subset of :class:`BotLike` — only the single plain ``send_message``
    the system-voice outage notice uses — so any ``BotLike`` satisfies it structurally and a
    test fake need not implement the whole gateway protocol.
    """

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object: ...


class _GuppiOutageNotifier:
    """Outage-notice adapter: GUPPI's honest "Bob unavailable" line into Bob's topic (BOB-049 .3).

    Realises HandleMessage's ``OutageNotifier`` seam. When an ESSENTIAL turn step (the
    semantic judgment or the reply generation) keeps failing after the bounded retries,
    Bob — the mind — is unavailable, so GUPPI (the infrastructure subsystem) honestly
    reports the outage rather than let a degraded half-answer ship («полный Боб или честный
    GUPPI-нотис»). The fixed third-person :data:`GUPPI_OUTAGE_TEXT` is posted as a plain
    system line into Bob's TOPIC (``message_thread_id == telegram.bob.topic_id``) so it
    lands in the live conversation thread and reads as GUPPI reporting, not Bob being rude.
    Transport only — the failure handling + best-effort swallow live in the use-case.
    """

    def __init__(
        self, *, bot: _PlainNotifyBot, chat_id: int, topic_id: int | None
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._topic_id = topic_id

    async def notify_outage(self) -> None:
        """Post GUPPI's honest outage notice into Bob's topic (system voice)."""
        await self._bot.send_message(
            chat_id=self._chat_id,
            text=GUPPI_OUTAGE_TEXT,
            message_thread_id=self._topic_id,
        )
