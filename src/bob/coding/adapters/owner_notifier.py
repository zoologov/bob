# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Coding owner-notifier adapter — stream a coding-session line through BOB'S bot (BOB-046 .1).

Realises the gated coding use-case's ``OwnerNotifier`` (structurally), so the assistant
streams the plan, the per-event narration and the PR url to the owner without knowing any
transport. By canon Bob is the speaker (the owner converses with Bob; GUPPI is the silent
executor), so the SENDER is Bob's bot; the messages thread back into Bob's TOPIC (BOB-042
Fix B) through the shared rich-markdown path. Extracted verbatim from the composition root
(BOB-062.7a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.infrastructure.telegram.gateway import RichMarkdownSender

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import MarkdownSendBot


class _CodingOwnerNotifier:
    """Owner-notifier adapter: send one coding-session line through BOB'S bot (BOB-046 .1).

    Realises the use-case's ``OwnerNotifier`` (structurally), so the gated coding assistant
    streams the plan, the per-event narration and the PR url to the owner without knowing
    any transport. By canon Bob is the one talking — the owner converses with Bob, GUPPI is
    the silent executor under the hood — so the SENDER is Bob's bot (BOB-046 .1); the
    per-event narrative text stays GUPPI-attributed («GUPPI: …») in
    :func:`~bob.coding.narrate.narrate` (only the sender changed). The owner gives
    Bob the task in BOB'S TOPIC (the BOB-041 natural-language path), so the session replies
    are threaded back into THAT topic via ``message_thread_id == telegram.bob.topic_id``
    (BOB-042 Fix B) — the conversation stays in one thread instead of splitting between
    Bob's topic (input) and General (output). Coding messages carry markdown (## headings,
    **bold**, ``code``), so they go through the shared :class:`RichMarkdownSender` rich
    path (BOB-041 .1) — the same conversion Bob's normal replies use — with a safe plain
    fallback so a parse error never drops a message.
    """

    def __init__(
        self, *, bot: MarkdownSendBot, chat_id: int, topic_id: int | None
    ) -> None:
        self._sender = RichMarkdownSender(bot)
        self._chat_id = chat_id
        self._topic_id = topic_id

    async def send(self, text: str) -> None:
        """Post ``text`` into Bob's topic through Bob's bot (rich markdown, threaded)."""
        await self._sender.send(
            chat_id=self._chat_id, markdown=text, message_thread_id=self._topic_id
        )
