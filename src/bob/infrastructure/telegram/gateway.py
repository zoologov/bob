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
2. **Streaming reply (drafts-first for every chat — BOB-007).** Given an async
   iterator of reply tokens, the gateway types "live":

   * **Primary — native drafts.** Partials stream through the native rich draft
     channel (``send_rich_message_draft``) as tokens arrive, pinned to
     ``reply_thread_id`` for topic messages. Rich blocks + a ``RichBlockThinking``
     block (when a ``thinking`` is present) stream natively. This is the native
     streaming mechanism, so it runs **unthrottled** (no edit-spam). With Threaded
     Mode enabled the peer accepts drafts in group forum topics too. The completed
     reply commits as a rich message (``send_rich_message``), degrading to plain
     ``send_message`` on a rich error. On a Telegram ``RetryAfter`` a draft backs off.
   * **Fallback — edit-streaming.** Only when a draft call raises
     ``TelegramBadRequest`` (e.g. a peer that still rejects drafts with
     ``TEXTDRAFT_PEER_INVALID``) the gateway switches to **incremental
     ``editMessageText``**: a plain **placeholder** carries the text streamed so
     far, then is edited with the accumulating plain text (throttled, respecting
     ``RetryAfter``, skipping no-op edits). On completion the **rich** final is sent
     and the placeholder **deleted** (a minor flicker is expected); if the rich send
     fails the placeholder is edited to the final plain text, and if that edit also
     fails a plain ``send_message`` is the last safety net — the reply is never lost.
     The 3.0s throttle stays **only** on this fallback edit path.

Time and sleeping are injected (``clock`` / ``sleep``) so batching/backoff are
deterministic in tests; the bot is injected behind a minimal :class:`BotLike`
protocol so tests use a fake aiogram bot — no real network. The concrete
aiogram ``Bot``/``Dispatcher`` wiring lives in ``bob.app``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from aiogram.exceptions import AiogramError, TelegramBadRequest, TelegramRetryAfter
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
    @property
    def message_thread_id(self) -> int | None: ...


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

    Intake uses ``get_updates``; the streaming reply streams progressive partials via
    the native rich draft channel (``send_rich_message_draft``) and commits the
    finished reply via ``send_rich_message``. The plain ``send_message_draft`` /
    ``edit_message_text`` / ``send_message`` calls back the edit-streaming fallback
    used when a peer rejects drafts.
    """

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]: ...

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike: ...

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> MessageLike | bool: ...

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool: ...

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,
    ) -> bool: ...

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike: ...

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
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
        reply_thread_id: int | None = None,
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
        # When set (the Bob bot), every outgoing reply is pinned to this topic
        # thread so Bob's replies land in his topic; ``None`` keeps the legacy
        # un-threaded behaviour (single-bot / General).
        self._reply_thread_id = reply_thread_id
        self._offset = 0
        self._seen_update_ids: set[int] = set()
        # Chats whose peer rejected a draft (e.g. a supergroup forum topic raises
        # ``TEXTDRAFT_PEER_INVALID``). Drafting is best-effort: once a chat refuses
        # a draft we stop attempting drafts there and only ever commit the final,
        # non-draft reply — so the user always gets an answer.
        self._draft_unsupported_chats: set[int] = set()
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
                chat_id=chat_id,
                text="Usage: /authorize <user_id>",
                message_thread_id=self._reply_thread_id,
            )
            return
        if grant:
            await self._authorizer.authorize(target)
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"Authorized user {target}.",
                message_thread_id=self._reply_thread_id,
            )
        else:
            await self._authorizer.deauthorize(target)
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"Deauthorized user {target}.",
                message_thread_id=self._reply_thread_id,
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
        self, *, chat_id: int, tokens: AsyncIterator[str], thinking: str | None = None
    ) -> int:
        """Type Bob's reply "live", drafts-first for **every** chat (BOB-007).

        The **primary** path is the native draft channel — smooth token streaming
        via ``send_rich_message_draft`` (rich blocks + a ``RichBlockThinking`` block
        when ``thinking`` is present stream natively), pinned to ``reply_thread_id``
        for topic messages, with **no edit throttle** (drafts are the native
        streaming mechanism, not edit-spam). This now covers group forum topics too:
        with Threaded Mode enabled the peer accepts drafts.

        The **fallback** (no regression) engages only when a draft call raises
        :class:`TelegramBadRequest` (e.g. a peer that still rejects drafts with
        ``TEXTDRAFT_PEER_INVALID``): the gateway switches to the throttled
        ``editMessageText`` placeholder stream and, failing that, a plain
        ``send_message`` — the BOB-004 safety net. The 3.0s throttle stays **only**
        on this fallback edit path. Either way the finished reply is always
        delivered. Returns the number of native drafts streamed before any fallback.
        """
        return await self._stream_reply_drafts_first(
            chat_id=chat_id, tokens=tokens, thinking=thinking
        )

    async def _stream_reply_drafts_first(
        self,
        *,
        chat_id: int,
        tokens: AsyncIterator[str],
        thinking: str | None,
    ) -> int:
        """Stream native rich drafts; on a draft rejection switch to edit-fallback.

        Drafts stream unthrottled until either the stream ends (then commit the rich
        final) or a draft raises :class:`TelegramBadRequest`. On a rejection the
        accumulated-so-far text seeds the throttled edit-streaming fallback, which
        drains the remaining tokens and commits the final — the reply is never lost.
        """
        accumulated = ""
        drafted_text = ""
        pending_tokens = 0
        drafts_made = 0

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            if pending_tokens < self._batch_tokens or accumulated == drafted_text:
                continue
            if not await self._try_rich_draft(chat_id, accumulated):
                # The peer rejected the draft: hand the rest of the turn (including
                # what we have so far) to the throttled edit-streaming fallback.
                return await self._stream_reply_live_edit(
                    chat_id=chat_id,
                    tokens=tokens,
                    thinking=thinking,
                    seed=accumulated,
                )
            drafted_text = accumulated
            drafts_made += 1
            pending_tokens = 0

        if accumulated or (thinking and thinking.strip()):
            await self.reply(chat_id=chat_id, markdown=accumulated, thinking=thinking)
        return drafts_made

    async def _try_rich_draft(self, chat_id: int, text: str) -> bool:
        """Stream ``text`` as one native rich draft (no throttle).

        Returns ``True`` on success, ``False`` when the peer rejects the draft with
        :class:`TelegramBadRequest` (the signal to fall back to edit-streaming). A
        transient ``RetryAfter`` backs off and retries; any other aiogram error is
        treated as a draft rejection so the reply still reaches the user.
        """
        rich_markdown = self._render(text, None)
        while True:
            try:
                await self._bot.send_rich_message_draft(
                    chat_id=chat_id,
                    draft_id=_DRAFT_ID,
                    rich_message=InputRichMessage(markdown=rich_markdown),
                    message_thread_id=self._reply_thread_id,
                )
                return True
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after)
                logger.warning(
                    "Telegram rate-limited rich draft; backing off %.1fs", wait
                )
                await self._sleep(wait)
            except (AiogramError, ValueError) as exc:
                self._mark_drafts_unsupported(chat_id, exc)
                return False

    async def _await_throttle(self, last_action_at: float | None) -> None:
        """Sleep so the next call is at least ``throttle_interval`` after the last.

        Used only on the **fallback** edit-streaming path (BOB-007): the primary
        native-draft path is unthrottled.
        """
        if last_action_at is None or self._throttle_interval <= 0:
            return
        elapsed = self._clock() - last_action_at
        remaining = self._throttle_interval - elapsed
        if remaining > 0:
            await self._sleep(remaining)

    # --- Live edit streaming (draft fallback) ---------------------------------

    async def _stream_reply_live_edit(
        self,
        *,
        chat_id: int,
        tokens: AsyncIterator[str],
        thinking: str | None,
        seed: str = "",
    ) -> int:
        """Type "live" via incremental ``editMessageText`` — the draft fallback.

        Engaged only when native drafts were rejected (BOB-007). A plain
        **placeholder** carries the first partial text into Bob's thread; as tokens
        arrive the placeholder is edited with the accumulating plain text
        (throttled, skipping no-op edits). On completion the **rich** final is sent
        and the placeholder deleted; if the rich send fails the placeholder is
        edited to the final plain text instead — the reply is never lost. ``seed`` is
        the text already accumulated on the draft path before it fell back, so no
        tokens are dropped. Returns the number of edits streamed.
        """
        accumulated = seed
        edited_text = ""
        pending_tokens = self._batch_tokens if seed else 0
        edits_made = 0
        placeholder_id: int | None = None
        last_edit_at: float | None = None

        if seed:
            placeholder_id = await self._send_placeholder(chat_id, seed)
            edited_text = seed
            pending_tokens = 0

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            if pending_tokens < self._batch_tokens or accumulated == edited_text:
                continue
            if placeholder_id is None:
                placeholder_id = await self._send_placeholder(chat_id, accumulated)
            else:
                last_edit_at = await self._edit(
                    chat_id, placeholder_id, accumulated, last_edit_at
                )
                edits_made += 1
            edited_text = accumulated
            pending_tokens = 0

        await self._finish_live_edit(
            chat_id, placeholder_id, accumulated, thinking, last_edit_at
        )
        return edits_made

    async def _send_placeholder(self, chat_id: int, text: str) -> int | None:
        """Send the live-typing placeholder; return its id (``None`` on failure)."""
        try:
            message = await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("live placeholder failed; will commit final only: %s", exc)
            return None
        return message.message_id

    async def _edit(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        last_edit_at: float | None,
    ) -> float:
        """Throttle, then edit the placeholder; return the edit time."""
        await self._await_throttle(last_edit_at)
        await self._edit_with_backoff(chat_id, message_id, text)
        return self._clock()

    async def _edit_with_backoff(
        self, chat_id: int, message_id: int, text: str
    ) -> bool:
        """Edit the placeholder, backing off on ``RetryAfter``; never crash a turn.

        Returns ``True`` when the edit landed, ``False`` when it failed (and was
        swallowed) — so the final-commit path can fall back to a plain send rather
        than silently losing the reply.
        """
        while True:
            try:
                await self._bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text
                )
                return True
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after)
                logger.warning("Telegram rate-limited edit; backing off %.1fs", wait)
                await self._sleep(wait)
            except (AiogramError, ValueError) as exc:
                logger.info("live edit failed (ignored): %s", exc)
                return False

    async def _finish_live_edit(
        self,
        chat_id: int,
        placeholder_id: int | None,
        accumulated: str,
        thinking: str | None,
        last_edit_at: float | None,
    ) -> None:
        """Commit the rich final and delete the placeholder; fall back on failure.

        Variant B: on a successful rich send the live placeholder is deleted so the
        rich final replaces it. If the rich send fails the placeholder is instead
        edited to the final plain text (the safety net of BEAD-01), so the reply is
        never lost — and the placeholder is never left empty.

        The rich final honours the **same throttle window** as the live edits
        (``last_edit_at``): firing ``send_rich_message`` immediately after the last
        ``editMessageText`` was the live ``SendRichMessage`` flood-control source
        (BOB-006). It is a **single** attempt — on a flood/``RetryAfter`` it degrades
        to the already-streamed placeholder (entity-plain) rather than retrying.
        """
        has_content = bool(accumulated) or bool(thinking and thinking.strip())
        if not has_content:
            await self._delete_placeholder(chat_id, placeholder_id)
            return
        await self._await_throttle(last_edit_at)
        if await self._send_rich_final(chat_id, accumulated, thinking):
            await self._delete_placeholder(chat_id, placeholder_id)
            return
        # Rich failed: deliver the final via the placeholder (edit) or a plain send.
        # If the placeholder edit also fails, a plain send is the last safety net so
        # the reply is never lost (draft -> edit -> plain).
        if placeholder_id is not None and await self._edit_with_backoff(
            chat_id, placeholder_id, accumulated
        ):
            return
        await self._send_plain(chat_id, accumulated)

    async def _delete_placeholder(
        self, chat_id: int, placeholder_id: int | None
    ) -> None:
        """Best-effort delete of the live placeholder (a failure never breaks a turn)."""
        if placeholder_id is None:
            return
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=placeholder_id)
        except (AiogramError, ValueError) as exc:
            logger.info("placeholder delete failed (ignored): %s", exc)

    async def _send_rich_final(
        self, chat_id: int, markdown: str, thinking: str | None
    ) -> bool:
        """Send the rich final into the thread; return ``True`` iff it succeeded."""
        rich_markdown = self._render(markdown, thinking)
        try:
            await self._bot.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(markdown=rich_markdown),
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("rich final failed; falling back to plain: %s", exc)
            return False
        return True

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
        if not await self._send_rich_final(chat_id, markdown, thinking):
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
        commit). Drafting is **best-effort**: a peer that rejects a draft
        (``TEXTDRAFT_PEER_INVALID`` in a forum topic) is remembered as
        draft-unsupported and the rest of the turn skips drafts. The completed reply
        is always committed via :meth:`reply`, whose rich error degrades to plain
        ``send_message`` so the answer still reaches the user. Returns the number of
        drafts streamed.
        """
        accumulated = ""
        drafted_text = ""
        pending_tokens = 0
        drafts_made = 0
        last_draft_at: float | None = None

        async for token in tokens:
            accumulated += token
            pending_tokens += 1
            should_draft = (
                pending_tokens >= self._batch_tokens
                and accumulated != drafted_text
                and chat_id not in self._draft_unsupported_chats
            )
            if should_draft:
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
                    message_thread_id=self._reply_thread_id,
                )
                return
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after)
                logger.warning(
                    "Telegram rate-limited rich draft; backing off %.1fs", wait
                )
                await self._sleep(wait)
            except (AiogramError, ValueError) as exc:
                self._mark_drafts_unsupported(chat_id, exc)
                return

    def _mark_drafts_unsupported(self, chat_id: int, exc: Exception) -> None:
        """Record that ``chat_id`` rejected a draft; skip drafts there from now on.

        Telegram rejects drafts for some peers (e.g. a supergroup forum topic raises
        ``TEXTDRAFT_PEER_INVALID``). Drafting is best-effort, so we swallow the error,
        remember the chat does not support drafts, and let the caller fall through to
        the non-draft final send — the user always gets the finished reply.
        """
        already_known = chat_id in self._draft_unsupported_chats
        self._draft_unsupported_chats.add(chat_id)
        if already_known:
            return
        if isinstance(exc, TelegramBadRequest):
            logger.info(
                "chat %d rejects drafts (%s); delivering reply without streaming",
                chat_id,
                exc,
            )
        else:
            logger.warning(
                "draft failed for chat %d; delivering reply without streaming: %s",
                chat_id,
                exc,
            )

    async def _send_plain(self, chat_id: int, text: str) -> None:
        """Send ``text`` as plain message(s), splitting on the length limit."""
        for chunk in _split_for_length(text):
            await self._bot.send_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=self._reply_thread_id,
            )


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
