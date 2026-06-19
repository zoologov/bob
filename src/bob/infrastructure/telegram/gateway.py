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
2. **Streaming reply.** Given an async iterator of reply tokens, it streams the
   partial text through aiogram's native **draft** channel
   (``send_message_draft``) — **batching** drafts by token count and
   **throttling** them to at most one per interval — then **commits** the
   completed reply as a real message (``send_message``). On a Telegram
   ``RetryAfter`` rate-limit it backs off and retries. (This replaces the old
   ``editMessageText`` loop; native drafts stream without breaking formatting.)

Time and sleeping are injected (``clock`` / ``sleep``) so batching/backoff are
deterministic in tests; the bot is injected behind a minimal :class:`BotLike`
protocol so tests use a fake aiogram bot — no real network. The concrete
aiogram ``Bot``/``Dispatcher`` wiring lives in ``bob.app``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from aiogram.exceptions import AiogramError, TelegramRetryAfter
from aiogram.types import InputRichMessage

from bob.application.runtime.events import MessageReceived
from bob.infrastructure.telegram.rich import (
    MarkdownToRichMessage,
    RichMessageSerializer,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    from bob.domain.ports import EventBus

logger = logging.getLogger(__name__)

__all__ = [
    "PLAIN_TEXT_LIMIT",
    "AuthorizerLike",
    "BotLike",
    "MessageLike",
    "TelegramGateway",
    "UpdateLike",
]

# Each streamed reply uses one draft slot; drafts share this id within a reply.
_DRAFT_ID = 1

# Telegram's hard cap on a single message's text; the plain fallback splits here.
PLAIN_TEXT_LIMIT = 4096


# --- Minimal structural views of the bits of aiogram the gateway touches ------


class MessageLike(Protocol):
    """The subset of a Telegram ``Message`` the gateway/bot adapter touches."""

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
    def message(self) -> MessageLike | None: ...
    @property
    def effective_chat(self) -> _ChatLike | None: ...
    @property
    def effective_user(self) -> _UserLike | None: ...


class BotLike(Protocol):
    """The subset of an aiogram ``Bot`` the gateway calls (keeps tests network-free).

    Intake uses ``get_updates``; the streaming reply uses the native draft channel
    (``send_message_draft``) for progressive partials and ``send_message`` to
    commit the finished reply.
    """

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]: ...

    async def send_message(self, *, chat_id: int, text: str) -> MessageLike: ...

    async def send_message_draft(
        self, *, chat_id: int, draft_id: int, text: str
    ) -> bool: ...

    async def send_rich_message(
        self, *, chat_id: int, rich_message: InputRichMessage
    ) -> MessageLike: ...

    async def send_rich_message_draft(
        self, *, chat_id: int, draft_id: int, rich_message: InputRichMessage
    ) -> bool: ...


class AuthorizerLike(Protocol):
    """The access-policy surface the gate calls (realised by ``Authorizer``).

    Defined structurally so the gateway stays decoupled from the application
    type while the hexagon still allows ``infrastructure → application``.
    """

    def is_owner(self, user_id: int | None) -> bool: ...
    async def is_authorized(self, *, user_id: int | None, chat_id: int) -> bool: ...
    async def authorize(self, user_id: int) -> None: ...
    async def deauthorize(self, user_id: int) -> None: ...


# Injected seams for deterministic timing.
type MonotonicClock = Callable[[], float]
type Sleep = Callable[[float], Awaitable[None]]

# Owner-only privileged commands handled at the gate (never published as messages).
_AUTHORIZE_COMMAND = "/authorize"
_DEAUTHORIZE_COMMAND = "/deauthorize"


class TelegramGateway:
    """Long-polling intake + throttled draft streaming over an injected bot."""

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
        authorizer: AuthorizerLike | None = None,
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
        self._authorizer = authorizer
        self._offset = 0
        self._seen_update_ids: set[int] = set()
        self._converter = MarkdownToRichMessage()
        self._serializer = RichMessageSerializer()

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
        """Deduplicate, authorize, normalise, and publish one update.

        The **single authorization gate** lives here: when an authorizer is wired,
        a message from a disallowed chat or an unauthorized user is **silently
        dropped** — no :class:`MessageReceived`, no reply. The owner's privileged
        ``/authorize``/``/deauthorize`` commands are consumed here too (never
        published). Returns ``True`` only when a :class:`MessageReceived` was
        published; ``False`` for a duplicate, an unusable update, a dropped one, or
        a consumed owner command.
        """
        if update.update_id in self._seen_update_ids:
            logger.debug("dropping duplicate update_id=%d", update.update_id)
            return False
        self._seen_update_ids.add(update.update_id)

        if not await self._passes_gate(update):
            return False

        event = self._to_message_received(update)
        if event is None:
            return False
        await self._bus.publish(event)
        return True

    async def _passes_gate(self, update: UpdateLike) -> bool:
        """Enforce authorization + privileged commands; the one bypass-free gate.

        Returns ``True`` when the update may proceed to publication, ``False`` when
        it was dropped (unauthorized / wrong chat) or consumed (owner command).
        With no authorizer wired the gate is open (backward-compatible).
        """
        if self._authorizer is None:
            return True
        chat = update.effective_chat
        if chat is None:
            return False
        user = update.effective_user
        user_id = user.id if user is not None else None
        if not await self._authorizer.is_authorized(
            user_id=user_id, chat_id=chat.id
        ):
            logger.info(
                "dropping unauthorized update from user=%s chat=%d",
                user_id,
                chat.id,
            )
            return False
        return not await self._handle_owner_command(update, chat.id, user_id)

    async def _handle_owner_command(
        self, update: UpdateLike, chat_id: int, user_id: int | None
    ) -> bool:
        """Consume an owner-only ``/authorize``/``/deauthorize`` command.

        Returns ``True`` when the update was a privileged command (handled here,
        not published). Only the owner may run these; for anyone else the command
        text falls through as an ordinary message.
        """
        assert self._authorizer is not None  # guarded by the caller
        message = update.message
        text = message.text if message is not None else None
        if text is None or not self._authorizer.is_owner(user_id):
            return False
        command, _, argument = text.strip().partition(" ")
        if command == _AUTHORIZE_COMMAND:
            await self._run_authorize(chat_id, argument, grant=True)
            return True
        if command == _DEAUTHORIZE_COMMAND:
            await self._run_authorize(chat_id, argument, grant=False)
            return True
        return False

    async def _run_authorize(
        self, chat_id: int, argument: str, *, grant: bool
    ) -> None:
        """Apply an ``/authorize``/``/deauthorize`` grant and confirm to the owner."""
        assert self._authorizer is not None  # guarded by the caller
        target = _parse_user_id(argument)
        if target is None:
            await self._bot.send_message(
                chat_id=chat_id, text="Usage: /authorize <user_id>"
            )
            return
        if grant:
            await self._authorizer.authorize(target)
            await self._bot.send_message(
                chat_id=chat_id, text=f"Authorized user {target}."
            )
        else:
            await self._authorizer.deauthorize(target)
            await self._bot.send_message(
                chat_id=chat_id, text=f"Deauthorized user {target}."
            )

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
        """Stream ``tokens`` as native drafts, then commit the finished reply.

        Partial text is sent through ``send_message_draft`` as tokens arrive: a
        draft is flushed once ``batch_tokens`` new tokens have accumulated,
        throttled to at most one draft per ``throttle_interval`` seconds. When the
        stream ends, the completed text (if any) is committed as a real message
        via ``send_message``. Returns the number of drafts streamed.
        """
        accumulated = ""
        drafted_text = ""
        pending_tokens = 0
        drafts_made = 0
        last_draft_at: float | None = None

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            if pending_tokens >= self._batch_tokens and accumulated != drafted_text:
                last_draft_at = await self._draft(
                    chat_id, accumulated, last_draft_at
                )
                drafted_text = accumulated
                drafts_made += 1
                pending_tokens = 0

        if accumulated:
            await self._bot.send_message(chat_id=chat_id, text=accumulated)

        return drafts_made

    async def _draft(
        self,
        chat_id: int,
        text: str,
        last_draft_at: float | None,
    ) -> float:
        """Throttle, then stream ``text`` as a draft; return the draft time."""
        await self._await_throttle(last_draft_at)
        await self._draft_with_backoff(chat_id, text)
        return self._clock()

    async def _await_throttle(self, last_draft_at: float | None) -> None:
        if last_draft_at is None or self._throttle_interval <= 0:
            return
        elapsed = self._clock() - last_draft_at
        remaining = self._throttle_interval - elapsed
        if remaining > 0:
            await self._sleep(remaining)

    async def _draft_with_backoff(self, chat_id: int, text: str) -> None:
        while True:
            try:
                await self._bot.send_message_draft(
                    chat_id=chat_id, draft_id=_DRAFT_ID, text=text
                )
                return
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after)
                logger.warning("Telegram rate-limited draft; backing off %.1fs", wait)
                await self._sleep(wait)

    # --- Rich reply -----------------------------------------------------------

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> None:
        """Send Bob's ``markdown`` reply as a native rich message.

        The markdown is converted to a typed rich-message tree (optionally led by
        a collapsible :class:`RichBlockThinking` block when ``thinking`` is given),
        serialized to rich-message markdown, and sent via ``send_rich_message``. On
        **any** rich failure the reply degrades silently to plain ``send_message``
        — the user always gets the text, never an error. An empty reply with no
        thinking sends nothing.
        """
        if not markdown.strip() and not (thinking and thinking.strip()):
            return
        rich_markdown = self._render(markdown, thinking)
        try:
            await self._bot.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(markdown=rich_markdown),
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("rich send failed; falling back to plain: %s", exc)
            await self._send_plain(chat_id, markdown)

    async def stream_reply_rich(
        self,
        *,
        chat_id: int,
        tokens: AsyncIterator[str],
        thinking: str | None = None,
    ) -> int:
        """Stream ``tokens`` as rich drafts, then commit the finished rich reply.

        Mirrors :meth:`stream_reply` but over the native rich channel
        (``send_rich_message_draft`` for partials, ``send_rich_message`` to
        commit). Any rich error on commit degrades to plain ``send_message`` so the
        completed reply still reaches the user. Returns the number of drafts
        streamed.
        """
        accumulated = ""
        drafted_text = ""
        pending_tokens = 0
        drafts_made = 0
        last_draft_at: float | None = None

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            if pending_tokens >= self._batch_tokens and accumulated != drafted_text:
                last_draft_at = await self._rich_draft(
                    chat_id, accumulated, last_draft_at
                )
                drafted_text = accumulated
                drafts_made += 1
                pending_tokens = 0

        if accumulated or (thinking and thinking.strip()):
            await self.reply(chat_id=chat_id, markdown=accumulated, thinking=thinking)

        return drafts_made

    def _render(self, markdown: str, thinking: str | None) -> str:
        message = self._converter.convert(markdown, thinking=thinking)
        return self._serializer.to_markdown(message)

    async def _rich_draft(
        self,
        chat_id: int,
        text: str,
        last_draft_at: float | None,
    ) -> float:
        """Throttle, then stream ``text`` as a rich draft; return the draft time."""
        await self._await_throttle(last_draft_at)
        await self._rich_draft_with_backoff(chat_id, text)
        return self._clock()

    async def _rich_draft_with_backoff(self, chat_id: int, text: str) -> None:
        rich_markdown = self._render(text, None)
        while True:
            try:
                await self._bot.send_rich_message_draft(
                    chat_id=chat_id,
                    draft_id=_DRAFT_ID,
                    rich_message=InputRichMessage(markdown=rich_markdown),
                )
                return
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after)
                logger.warning(
                    "Telegram rate-limited rich draft; backing off %.1fs", wait
                )
                await self._sleep(wait)
            except (AiogramError, ValueError) as exc:
                logger.warning("rich draft failed; skipping partial: %s", exc)
                return

    async def _send_plain(self, chat_id: int, text: str) -> None:
        """Send ``text`` as plain message(s), splitting on the length limit."""
        for chunk in _split_for_length(text):
            await self._bot.send_message(chat_id=chat_id, text=chunk)


def _parse_user_id(argument: str) -> int | None:
    """Parse the ``<user_id>`` argument of an owner command; ``None`` if invalid."""
    cleaned = argument.strip()
    if not cleaned.lstrip("-").isdigit():
        return None
    return int(cleaned)


def _split_for_length(text: str) -> list[str]:
    """Split ``text`` into chunks no longer than :data:`PLAIN_TEXT_LIMIT`."""
    if len(text) <= PLAIN_TEXT_LIMIT:
        return [text]
    return [
        text[start : start + PLAIN_TEXT_LIMIT]
        for start in range(0, len(text), PLAIN_TEXT_LIMIT)
    ]
