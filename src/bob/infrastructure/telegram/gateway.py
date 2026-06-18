# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""TelegramGateway — long-polling intake and streaming reply (transport only).

The gateway is the boundary between Telegram and the GUPPI application. It does
two transport jobs and *no* Higher-Mind / LLM / memory logic:

1. **Intake.** Long-polls Telegram (``get_updates``), **deduplicates** by
   ``update_id`` (Telegram may redeliver), normalises each text update into a
   :class:`MessageReceived`, and publishes it onto the :class:`EventBus`. A
   use-case elsewhere decides what to do.
2. **Streaming reply.** Given an async iterator of reply tokens, it sends one
   placeholder message then progressively edits it (``editMessageText``),
   **batching** edits by token count and **throttling** them to at most one per
   interval. On a Telegram ``RetryAfter`` rate-limit it backs off and retries.

Time and sleeping are injected (``clock`` / ``sleep``) so batching/backoff are
deterministic in tests; the bot is injected behind a minimal :class:`BotLike`
protocol so tests use a fake — no real network.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from telegram.error import RetryAfter

from bob.infrastructure.telegram.events import MessageReceived

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    from bob.domain.ports import EventBus

logger = logging.getLogger(__name__)

__all__ = ["BotLike", "TelegramGateway", "UpdateLike"]


# --- Minimal structural views of the bits of PTB the gateway touches ----------


class _MessageLike(Protocol):
    @property
    def message_id(self) -> int: ...
    @property
    def text(self) -> str | None: ...


class _ChatLike(Protocol):
    @property
    def id(self) -> int: ...


class _UserLike(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def full_name(self) -> str: ...


class UpdateLike(Protocol):
    """The subset of a Telegram ``Update`` the gateway reads."""

    @property
    def update_id(self) -> int: ...
    @property
    def message(self) -> _MessageLike | None: ...
    @property
    def effective_chat(self) -> _ChatLike | None: ...
    @property
    def effective_user(self) -> _UserLike | None: ...


class BotLike(Protocol):
    """The subset of a PTB ``Bot`` the gateway calls (keeps tests network-free)."""

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]: ...

    async def send_message(self, *, chat_id: int, text: str) -> _MessageLike: ...

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> object: ...


# Injected seams for deterministic timing.
type MonotonicClock = Callable[[], float]
type Sleep = Callable[[float], Awaitable[None]]


class TelegramGateway:
    """Long-polling intake + throttled streaming reply over an injected bot."""

    def __init__(
        self,
        *,
        bot: BotLike,
        bus: EventBus,
        poll_timeout: int,
        batch_tokens: int,
        throttle_interval: float,
        clock: MonotonicClock,
        sleep: Sleep,
    ) -> None:
        if batch_tokens < 1:
            raise ValueError("batch_tokens must be >= 1")
        if throttle_interval < 0:
            raise ValueError("throttle_interval must be >= 0")
        self._bot = bot
        self._bus = bus
        self._poll_timeout = poll_timeout
        self._batch_tokens = batch_tokens
        self._throttle_interval = throttle_interval
        self._clock = clock
        self._sleep = sleep
        self._offset = 0
        self._seen_update_ids: set[int] = set()

    # --- Intake ---------------------------------------------------------------

    async def poll_once(self) -> int:
        """Pull one batch of updates, dispatch each, advance the offset.

        Returns the number of updates that were newly published this poll.
        """
        updates = await self._bot.get_updates(
            offset=self._offset, timeout=self._poll_timeout
        )
        published = 0
        for update in updates:
            self._offset = max(self._offset, update.update_id + 1)
            if await self.intake(update):
                published += 1
        return published

    async def intake(self, update: UpdateLike) -> bool:
        """Deduplicate, normalise, and publish one update.

        Returns ``True`` when a :class:`MessageReceived` was published, ``False``
        when the update was a duplicate or carried no usable text.
        """
        if update.update_id in self._seen_update_ids:
            logger.debug("dropping duplicate update_id=%d", update.update_id)
            return False
        self._seen_update_ids.add(update.update_id)

        event = self._to_message_received(update)
        if event is None:
            return False
        await self._bus.publish(event)
        return True

    @staticmethod
    def _to_message_received(update: UpdateLike) -> MessageReceived | None:
        message = update.message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return None
        user = update.effective_user
        return MessageReceived(
            update_id=update.update_id,
            chat_id=chat.id,
            message_id=message.message_id,
            text=message.text,
            sender_id=user.id if user is not None else None,
            sender_name=user.full_name if user is not None else None,
        )

    # --- Streaming reply ------------------------------------------------------

    async def stream_reply(
        self, *, chat_id: int, tokens: AsyncIterator[str]
    ) -> int:
        """Stream ``tokens`` into a single message via batched, throttled edits.

        Sends one placeholder message, then edits it as tokens arrive: an edit is
        flushed once ``batch_tokens`` new tokens have accumulated, throttled to at
        most one edit per ``throttle_interval`` seconds. A final flush emits any
        remainder. Returns the number of edits performed.
        """
        placeholder = await self._bot.send_message(chat_id=chat_id, text="…")
        message_id = placeholder.message_id

        accumulated = ""
        sent_text = ""
        pending_tokens = 0
        edits_made = 0
        last_edit_at: float | None = None

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            if pending_tokens >= self._batch_tokens and accumulated != sent_text:
                last_edit_at = await self._edit(
                    chat_id, message_id, accumulated, last_edit_at
                )
                sent_text = accumulated
                edits_made += 1
                pending_tokens = 0

        if accumulated != sent_text:
            await self._edit(chat_id, message_id, accumulated, last_edit_at)
            edits_made += 1

        return edits_made

    async def _edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        last_edit_at: float | None,
    ) -> float:
        """Throttle, then edit the message to ``text``; return the edit time."""
        await self._await_throttle(last_edit_at)
        await self._edit_with_backoff(chat_id, message_id, text)
        return self._clock()

    async def _await_throttle(self, last_edit_at: float | None) -> None:
        if last_edit_at is None or self._throttle_interval <= 0:
            return
        elapsed = self._clock() - last_edit_at
        remaining = self._throttle_interval - elapsed
        if remaining > 0:
            await self._sleep(remaining)

    async def _edit_with_backoff(
        self, chat_id: int, message_id: int, text: str
    ) -> None:
        while True:
            try:
                await self._bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text
                )
                return
            except RetryAfter as exc:
                wait = _retry_after_seconds(exc)
                logger.warning("Telegram rate-limited edit; backing off %.1fs", wait)
                await self._sleep(wait)


def _retry_after_seconds(exc: RetryAfter) -> float:
    """Seconds to wait from a ``RetryAfter`` (int or, in future PTB, timedelta)."""
    value = exc.retry_after
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value)
