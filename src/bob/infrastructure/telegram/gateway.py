# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""TelegramGateway — long-polling intake and a typing-then-rich reply (transport only).

The gateway is the boundary between Telegram and the GUPPI application. It does
two transport jobs and *no* Higher-Mind / LLM / memory logic:

1. **Intake.** Long-polls Telegram (``get_updates``), **deduplicates** by
   ``update_id`` (Telegram may redeliver), normalises each text update into a
   :class:`MessageReceived`, and publishes it onto the :class:`EventBus`. A
   use-case elsewhere decides what to do.
2. **Reply (BOB-009 — typing keepalive + one rich final).** Native token
   streaming is impossible in a Telegram **group** topic — drafts are DM-only
   (Threaded Mode = DM topics, not group topics) and ``editMessageText`` in groups
   is slow and flood-prone. Bob is reached **only** through the group (DMs are
   closed by authz), so the gateway never streams. Instead it exposes:

   * :meth:`typing_indicator` — an async context manager wrapping the **slow
     generation**. On enter it fires ``sendChatAction("typing")`` into Bob's
     thread (``reply_thread_id``) immediately, then a background task **re-sends**
     it every ``typing_interval`` seconds (Telegram auto-clears typing after a few
     seconds), so "Bob is typing…" stays visible for the whole real wait. On exit
     it **cancels** that task (no leak). A failed typing action is logged and
     swallowed — it never breaks the turn.
   * :meth:`reply` — commits the finished reply as **one** rich message
     (``send_rich_message`` — headings/lists/code/quotes + a
     :class:`RichBlockThinking` block when a ``thinking`` is present), pinned to
     ``reply_thread_id``; on **any** rich error it degrades to a plain
     ``send_message`` so the reply is never lost. A single non-draft
     ``send_rich_message`` works in group topics.

Sleeping is injected (``sleep``) so the keepalive cadence is deterministic in
tests (``clock`` is kept on the seam for callers); the bot is injected behind a
minimal :class:`BotLike`
protocol so tests use a fake aiogram bot — no real network. The concrete aiogram
``Bot``/``Dispatcher`` wiring lives in ``bob.app``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from aiogram.exceptions import AiogramError
from aiogram.types import InputRichMessage, ReactionTypeEmoji

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
    "BotIdentitySignals",
    "BotLike",
    "MessageEntityLike",
    "MessageLike",
    "TelegramGateway",
    "UpdateLike",
]

# Telegram message-entity types that mark an @mention of a user (BOB-023).
_MENTION_TYPE = "mention"  # ``@username`` — the username is the entity's text slice.
_TEXT_MENTION_TYPE = "text_mention"  # a user without a username — carries ``user``.

# Telegram's hard cap on a single message's text; the plain fallback splits here.
PLAIN_TEXT_LIMIT = 4096

# The chat action Bob shows while assembling a reply ("Bob is typing…").
_TYPING_ACTION = "typing"

# The brief textual acknowledgement Bob sends when a native reaction is rejected
# (best-effort fallback) — a short "noted" so a react-only turn still lands a sign
# of life rather than going silent. Russian persona text (project language).
_REACTION_FALLBACK_ACK = "Угу."  # noqa: RUF001 — Cyrillic ack is intentional


# --- Minimal structural views of the bits of aiogram the gateway touches ------


class _UserLike(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def full_name(self) -> str: ...


class _BotUserLike(Protocol):
    """The subset of the aiogram ``User`` returned by ``Bot.get_me()`` we read.

    The composition root resolves Bob's bot identity once at startup via
    ``get_me`` and threads it into the gateway as :class:`BotIdentitySignals`; the
    addressivity scan needs only the bot's numeric ``id`` and ``@username``.
    """

    @property
    def id(self) -> int: ...
    @property
    def username(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class BotIdentitySignals:
    """Bob's own bot identity (BOB-023), resolved once at startup via ``get_me``.

    Threaded into the gateway so the addressivity scan can tell a mention of
    *Bob* (this ``user_id`` / ``@username``) from a mention of someone else. The
    GUPPI inner gateway is wired without it (mentions cannot be resolved → never
    a Bob mention), so it is optional.
    """

    user_id: int
    username: str | None


class MessageEntityLike(Protocol):
    """The subset of a Telegram ``MessageEntity`` the addressivity scan reads.

    A ``mention`` entity (``@username``) carries no ``user``; the username is the
    text slice ``text[offset : offset + length]``. A ``text_mention`` entity (a
    user without a username) carries the mentioned ``user`` instead.
    """

    @property
    def type(self) -> str: ...
    @property
    def offset(self) -> int: ...
    @property
    def length(self) -> int: ...
    @property
    def user(self) -> _UserLike | None: ...


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

    Intake uses ``get_updates``. The reply path shows a typing indicator
    (``send_chat_action``) while it assembles the reply, then commits it via the
    native ``send_rich_message`` — degrading to a plain ``send_message`` on a rich
    error so the reply is never lost.
    """

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]: ...

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike: ...

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool: ...

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike: ...

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[ReactionTypeEmoji],
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
    """Long-polling intake + a typing-indicator-then-rich-final reply over a bot."""

    def __init__(
        self,
        *,
        bot: BotLike,
        bus: EventBus,
        poll_timeout: int,
        typing_interval: float,
        clock: MonotonicClock,
        sleep: Sleep,
        authorizer: AuthorizerLike | None = None,
        reply_thread_id: int | None = None,
        bob_identity: BotIdentitySignals | None = None,
    ) -> None:
        if typing_interval <= 0:
            raise ValueError("typing_interval must be > 0")
        self._bot = bot
        self._bus = bus
        self._poll_timeout = poll_timeout
        self._typing_interval = typing_interval
        self._clock = clock
        self._sleep = sleep
        self._authorizer = authorizer
        # Bob's own bot identity (BOB-023), if known: lets the addressivity scan
        # tell an @mention of Bob from a mention of someone else. ``None`` (e.g.
        # the GUPPI inner gateway) means mentions cannot be resolved.
        self._bob_identity = bob_identity
        # When set (the Bob bot), every outgoing reply — and the typing action —
        # is pinned to this topic thread so Bob's replies land in his topic;
        # ``None`` keeps the legacy un-threaded behaviour (single-bot / General).
        self._reply_thread_id = reply_thread_id
        self._offset = 0
        self._seen_update_ids: set[int] = set()
        self._converter = MarkdownToRichMessage()
        self._serializer = RichMessageSerializer()

    def set_bob_identity(self, identity: BotIdentitySignals) -> None:
        """Wire Bob's own bot identity after construction (BOB-023).

        Resolved once at startup from ``get_me`` (an async call the synchronous
        constructor cannot make), so the addressivity scan can tell a mention of
        Bob from one of someone else.
        """
        self._bob_identity = identity

    def bob_user_id(self) -> int | None:
        """Bob's own bot ``user_id``, or ``None`` until identity is resolved (BOB-023).

        Read lazily by the addressivity policy in the use-case: the id is resolved
        asynchronously at startup (``get_me``), long after the synchronous
        composition root wired the gateway, so this returns ``None`` until then (and
        for the GUPPI gateway, which has no Bob identity) — a graceful degrade where
        reply-to-Bob cannot fire but @mention-of-Bob still does.
        """
        identity = self._bob_identity
        return identity.user_id if identity is not None else None

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

    def _to_message_received(self, update: UpdateLike) -> MessageReceived | None:
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
            reply_to_sender_id=_reply_to_sender_id(message),
            mentions_bob=self._mentions_bob(message),
        )

    def _mentions_bob(self, message: MessageLike) -> bool:
        """Whether ``message`` @mentions Bob's own bot (BOB-023).

        Scans the Telegram ``entities`` for an @mention of Bob — a ``mention``
        entity whose text slice is Bob's ``@username``, or a ``text_mention``
        entity carrying Bob's user id. Without a known bot identity (the GUPPI
        inner gateway) mentions cannot be resolved, so it is never a Bob mention.
        """
        identity = self._bob_identity
        if identity is None:
            return False
        text = message.text
        if text is None:
            return False
        for entity in getattr(message, "entities", None) or ():
            if _entity_mentions_bob(entity, text=text, identity=identity):
                return True
        return False

    # --- Reply (typing keepalive + one rich final) ----------------------------

    @contextlib.asynccontextmanager
    async def typing_indicator(self, *, chat_id: int) -> AsyncIterator[None]:
        """Keep "Bob is typing…" visible for the whole (slow) generation.

        BOB-009: the slow ``router.run`` runs INSIDE this context. On enter it fires
        one ``sendChatAction("typing")`` into ``reply_thread_id`` immediately, then
        spawns a background task that re-sends it every ``typing_interval`` seconds
        (the injected ``sleep`` drives the cadence, deterministic in tests) so the
        indicator never lapses while the model thinks. On exit the task is
        **cancelled** and awaited — no leaked task. A failed typing action is logged
        and swallowed, so it can never break the turn.
        """
        await self._send_typing(chat_id)
        task = asyncio.create_task(self._typing_keepalive(chat_id))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _typing_keepalive(self, chat_id: int) -> None:
        """Re-send the typing action every ``typing_interval`` until cancelled."""
        while True:
            await self._sleep(self._typing_interval)
            await self._send_typing(chat_id)

    async def _send_typing(self, chat_id: int) -> int:
        """Send one ``sendChatAction("typing")`` into the thread (best-effort).

        Returns ``1`` when the action landed, ``0`` when it failed — a failed typing
        action is logged and swallowed so it can never break a turn.
        """
        try:
            await self._bot.send_chat_action(
                chat_id=chat_id,
                action=_TYPING_ACTION,
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.info("typing action failed (ignored): %s", exc)
            return 0
        return 1

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

    def _render(self, markdown: str, thinking: str | None) -> str:
        message = self._converter.convert(markdown, thinking=thinking)
        return self._serializer.to_markdown(message)

    async def _send_plain(self, chat_id: int, text: str) -> None:
        """Send ``text`` as plain message(s), splitting on the length limit."""
        for chunk in _split_for_length(text):
            await self._bot.send_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=self._reply_thread_id,
            )

    # --- React-only (native reaction + best-effort fallback) ------------------

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        """Set a single native ``emoji`` reaction on ``message_id`` (best-effort).

        BOB-018: a react-only turn acknowledges with one native Telegram reaction
        instead of a composed reply. ``emoji`` is a standard-reaction emoji Bob
        picked from his mood. On **any** reaction error (the API rejects the emoji,
        a flaky connection) the reaction degrades to a brief textual ack so the
        user still gets a sign of life; it is logged and swallowed, so a failed
        reaction can never break a turn.
        """
        try:
            await self._bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning(
                "reaction failed; falling back to a brief ack: %s", exc
            )
            await self._send_plain(chat_id, _REACTION_FALLBACK_ACK)


def _reply_to_sender_id(message: MessageLike) -> int | None:
    """The from-user id of the message ``message`` replies to (``None`` if not a reply)."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    replied_user = replied.from_user
    return replied_user.id if replied_user is not None else None


def _entity_mentions_bob(
    entity: MessageEntityLike, *, text: str, identity: BotIdentitySignals
) -> bool:
    """Whether a single entity is an @mention of Bob's bot (BOB-023).

    A ``mention`` entity carries no ``user``; its text slice is ``@username`` —
    compared (case-insensitively, sans the leading ``@``) to Bob's username. A
    ``text_mention`` entity carries the mentioned ``user`` — matched on Bob's id.
    """
    if entity.type == _MENTION_TYPE:
        if identity.username is None:
            return False
        slice_ = text[entity.offset : entity.offset + entity.length]
        return slice_.lstrip("@").casefold() == identity.username.casefold()
    if entity.type == _TEXT_MENTION_TYPE:
        user = entity.user
        return user is not None and user.id == identity.user_id
    return False


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
