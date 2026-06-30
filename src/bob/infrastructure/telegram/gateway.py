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
from aiogram.types import BufferedInputFile, InputRichMessage, ReactionTypeEmoji

from bob.application.runtime.events import BobMessageReaction, MessageReceived
from bob.infrastructure.telegram.rich import (
    MarkdownToRichMessage,
    RichMessageSerializer,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

    from bob.domain.ports import EventBus

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_UPDATES",
    "PLAIN_TEXT_LIMIT",
    "AuthorizerLike",
    "BobMessageFilter",
    "BotIdentitySignals",
    "BotLike",
    "BotUserLike",
    "MarkdownSendBot",
    "MessageEntityLike",
    "MessageLike",
    "MessageReactionCountUpdatedLike",
    "MessageReactionUpdatedLike",
    "RichMarkdownSender",
    "TelegramGateway",
    "UpdateLike",
    "is_reaction_update",
]

# The update types Bob asks Telegram to deliver. ``message_reaction`` and
# ``message_reaction_count`` (BOB-050) are NOT in Telegram's default set, so they
# must be requested explicitly; ``message`` keeps ordinary intake working. The
# transport boundary (the aiogram adapter) passes this on every ``get_updates``.
ALLOWED_UPDATES: tuple[str, ...] = (
    "message",
    "message_reaction",
    "message_reaction_count",
)

# Telegram message-entity types that mark an @mention of a user (BOB-023).
_MENTION_TYPE = "mention"  # ``@username`` — the username is the entity's text slice.
_TEXT_MENTION_TYPE = "text_mention"  # a user without a username — carries ``user``.

# Telegram's hard cap on a single message's text; the plain fallback splits here.
PLAIN_TEXT_LIMIT = 4096

# The chat action Bob shows while assembling a reply ("Bob is typing…").
_TYPING_ACTION = "typing"

# The filename a rendered diagram PNG is sent under (BOB-035); Telegram only needs a
# stable name with the right extension for the inline-image preview.
_DIAGRAM_FILENAME = "diagram.png"

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


class BotUserLike(Protocol):
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


class MessageReactionUpdatedLike(Protocol):
    """The subset of a Telegram ``MessageReactionUpdated`` the gateway reads (BOB-050).

    A per-user reaction change: ``old_reaction`` / ``new_reaction`` are the reactor's
    reaction lists before and after the change (the diff yields added/removed emoji);
    ``user`` is who reacted (``None`` for an anonymous/channel actor). Reaction items
    are read structurally via their ``emoji`` attribute, so non-emoji (custom/paid)
    reactions are simply skipped.
    """

    @property
    def chat(self) -> _ChatLike: ...
    @property
    def message_id(self) -> int: ...
    @property
    def user(self) -> _UserLike | None: ...
    @property
    def old_reaction(self) -> Sequence[object]: ...
    @property
    def new_reaction(self) -> Sequence[object]: ...


class MessageReactionCountUpdatedLike(Protocol):
    """The subset of a Telegram ``MessageReactionCountUpdated`` the gateway reads (BOB-050).

    The anonymous aggregate a private group delivers: ``reactions`` are the emoji
    totals currently on the message, with no per-user diff and no actor — used for
    the defensive "someone reacted" signal.
    """

    @property
    def chat(self) -> _ChatLike: ...
    @property
    def message_id(self) -> int: ...
    @property
    def reactions(self) -> Sequence[object]: ...


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


class BobMessageFilter(Protocol):
    """Tells whether a reacted-to ``message_id`` is one of Bob's own messages (BOB-050).

    The reaction route publishes a :class:`BobMessageReaction` **only** for a
    reaction on a message Bob himself sent — looked up by the ``message_id`` recorded
    when Bob's reply was persisted. The concrete adapter wraps the episodic store; a
    reaction on a message with no matching episode is dropped gracefully.
    """

    async def is_bob_message(self, message_id: int) -> bool: ...


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

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike: ...

    async def send_document(
        self,
        *,
        chat_id: int,
        document: BufferedInputFile,
        caption: str | None = None,
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
        bob_reaction_filter: BobMessageFilter | None = None,
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
        # The "is this Bob's own message?" lookup the reaction route filters on
        # (BOB-050). ``None`` (e.g. the GUPPI inner gateway, or before it is wired)
        # means no reaction can be attributed to Bob → reaction updates are dropped.
        self._bob_reaction_filter = bob_reaction_filter
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

        Returns the number of updates that were newly published this poll. A
        reaction update (BOB-050) is dispatched to :meth:`intake_reaction`; an
        ordinary text update to :meth:`intake`.
        """
        updates = await self._bot.get_updates(
            offset=self._offset, timeout=self._poll_timeout
        )
        published = 0
        for update in updates:
            self._offset = max(self._offset, update.update_id + 1)
            if await self._dispatch(update):
                published += 1
        return published

    async def _dispatch(self, update: UpdateLike) -> bool:
        """Route one update: a reaction to the reaction path, else ordinary intake."""
        if is_reaction_update(update):
            return await self.intake_reaction(update)
        return await self.intake(update)

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

    # --- Reaction intake (BOB-050) --------------------------------------------

    async def intake_reaction(self, update: UpdateLike) -> bool:
        """Translate a reaction update into a :class:`BobMessageReaction` and publish it.

        Filters to reactions on **Bob's own** messages (the ``message_id`` matches a
        recorded outgoing Bob reply, via the injected :class:`BobMessageFilter`); a
        reaction on anyone else's message — or any reaction with no filter wired — is
        dropped. A per-user ``message_reaction`` yields the added/removed-emoji diff +
        the reactor's identity; an anonymous ``message_reaction_count`` yields the
        defensive "someone reacted" signal (``reactor_sender_id=None``). Deduplicated
        by ``update_id`` (Telegram may redeliver). Returns ``True`` iff an event was
        published.
        """
        if update.update_id in self._seen_update_ids:
            logger.debug("dropping duplicate reaction update_id=%d", update.update_id)
            return False
        self._seen_update_ids.add(update.update_id)
        reaction = _reaction_of(update)
        if reaction is not None:
            return await self._publish_user_reaction(reaction)
        count = _reaction_count_of(update)
        if count is not None:
            return await self._publish_anonymous_reaction(count)
        return False

    async def _publish_user_reaction(
        self, reaction: MessageReactionUpdatedLike
    ) -> bool:
        """Publish a per-user reaction (added/removed diff + reactor) if it is Bob's."""
        if not await self._is_bob_message(reaction.message_id):
            return False
        added, removed = _reaction_diff(reaction.old_reaction, reaction.new_reaction)
        if not added and not removed:
            return False
        user = reaction.user
        await self._bus.publish(
            BobMessageReaction(
                chat_id=reaction.chat.id,
                message_id=reaction.message_id,
                emoji_added=added,
                emoji_removed=removed,
                reactor_sender_id=user.id if user is not None else None,
                reactor_name=user.full_name if user is not None else None,
            )
        )
        return True

    async def _publish_anonymous_reaction(
        self, count: MessageReactionCountUpdatedLike
    ) -> bool:
        """Publish the defensive anonymous "someone reacted" signal if it is Bob's."""
        if not await self._is_bob_message(count.message_id):
            return False
        emojis = _count_emojis(count.reactions)
        if not emojis:
            return False
        await self._bus.publish(
            BobMessageReaction(
                chat_id=count.chat.id,
                message_id=count.message_id,
                emoji_added=emojis,
                emoji_removed=(),
                reactor_sender_id=None,
                reactor_name=None,
            )
        )
        return True

    async def _is_bob_message(self, message_id: int) -> bool:
        """Whether ``message_id`` is one of Bob's recorded outgoing messages."""
        if self._bob_reaction_filter is None:
            return False
        return await self._bob_reaction_filter.is_bob_message(message_id)

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
    ) -> int | None:
        """Send Bob's ``markdown`` reply as a native rich message.

        The markdown is converted to a typed rich-message tree (optionally led by
        a collapsible :class:`RichBlockThinking` block when ``thinking`` is given),
        serialized to rich-message markdown, and sent via ``send_rich_message``. On
        **any** rich failure the reply degrades silently to plain ``send_message``
        — the user always gets the text, never an error. An empty reply with no
        thinking sends nothing.

        Returns the Telegram ``message_id`` of the sent message (the first chunk
        when the plain fallback splits a long reply), so the caller can record which
        message was Bob's reply (BOB-050) and later link a reaction back to it.
        ``None`` when nothing was sent.
        """
        if not markdown.strip() and not (thinking and thinking.strip()):
            return None
        message_id = await self._send_rich_final(chat_id, markdown, thinking)
        if message_id is not None:
            return message_id
        return await self._send_plain(chat_id, markdown)

    async def _send_rich_final(
        self, chat_id: int, markdown: str, thinking: str | None
    ) -> int | None:
        """Send the rich final into the thread; return its ``message_id`` (``None`` on failure)."""
        rich_markdown = self._render(markdown, thinking)
        try:
            sent = await self._bot.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(markdown=rich_markdown),
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("rich final failed; falling back to plain: %s", exc)
            return None
        return sent.message_id

    def _render(self, markdown: str, thinking: str | None) -> str:
        message = self._converter.convert(markdown, thinking=thinking)
        return self._serializer.to_markdown(message)

    async def _send_plain(self, chat_id: int, text: str) -> int | None:
        """Send ``text`` as plain message(s); return the first chunk's ``message_id``."""
        first_message_id: int | None = None
        for chunk in _split_for_length(text):
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=self._reply_thread_id,
            )
            if first_message_id is None:
                first_message_id = sent.message_id
        return first_message_id

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

    # --- Photo (render_diagram → PNG into the chat) ---------------------------

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None:
        """Send ``photo`` (PNG bytes) as a Telegram photo, pinned to Bob's thread (BOB-035).

        The transport half of the ``render_diagram`` skill: the rendered PNG is posted
        as a native photo (tap-to-zoom) into ``chat_id`` / ``reply_thread_id`` with an
        optional short ``caption``. The bytes are wrapped in an aiogram
        ``BufferedInputFile`` so no temp file is needed at the transport boundary. On
        any transport error the failure is logged and swallowed (the use-case already
        treats the send as best-effort), so a failed photo can never break the turn.
        """
        try:
            await self._bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(photo, filename=_DIAGRAM_FILENAME),
                caption=caption,
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("sending a diagram photo failed (ignored): %s", exc)

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None:
        """Send ``document`` (PNG bytes) as an uncompressed file, pinned to the thread (BOB-037).

        The readability transport for a rendered diagram: Telegram ``send_photo``
        recompresses to JPEG and caps the long side (~1280px), so a dense diagram goes
        unreadable. Posting the PNG as a DOCUMENT keeps it byte-for-byte and full
        resolution (tap → pan/zoom the real pixels). The bytes are wrapped in an
        aiogram ``BufferedInputFile`` under a stable ``diagram.png`` filename so no temp
        file is needed at the transport boundary. On any transport error the failure is
        logged and swallowed (the use-case already treats the send as best-effort), so a
        failed document can never break the turn.
        """
        try:
            await self._bot.send_document(
                chat_id=chat_id,
                document=BufferedInputFile(document, filename=_DIAGRAM_FILENAME),
                caption=caption,
                message_thread_id=self._reply_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("sending a diagram document failed (ignored): %s", exc)


class MarkdownSendBot(Protocol):
    """The narrow bot surface :class:`RichMarkdownSender` needs (rich + plain send).

    Interface-segregated subset of :class:`BotLike` — only the two send calls the rich
    seam uses — so any ``BotLike`` satisfies it structurally and a test fake need not
    implement the whole gateway protocol.
    """

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike: ...

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike: ...


class RichMarkdownSender:
    """Send markdown as a native rich message, degrading to plain text on a rich error.

    The shared rich-send seam (BOB-041 .1): the same markdown → ``send_rich_message``
    conversion Bob's normal :meth:`TelegramGateway.reply` uses, factored out so other
    owner-facing channels — the gated coding assistant's owner-notifier — render
    headings / **bold** / ``code`` instead of leaking raw markdown. On **any** rich
    failure it falls back to a plain ``send_message`` (split on the length limit), so a
    parse error never loses the message. Stateless apart from the pure converter +
    serializer, so it is reused across chats/threads via the per-call arguments.
    """

    def __init__(self, bot: MarkdownSendBot) -> None:
        self._bot = bot
        self._converter = MarkdownToRichMessage()
        self._serializer = RichMessageSerializer()

    async def send(
        self, *, chat_id: int, markdown: str, message_thread_id: int | None = None
    ) -> None:
        """Send ``markdown`` as a rich message; degrade to plain text on a rich error.

        An empty/blank ``markdown`` sends nothing. The rich path is tried first; on a
        rich (parse/transport) failure the text is sent plain so it is never lost.
        """
        if not markdown.strip():
            return
        if not await self._send_rich(chat_id, markdown, message_thread_id):
            await self._send_plain(chat_id, markdown, message_thread_id)

    async def _send_rich(
        self, chat_id: int, markdown: str, message_thread_id: int | None
    ) -> bool:
        """Send the rich message; return ``True`` iff it succeeded (``False`` → fall back)."""
        rich_markdown = self._serializer.to_markdown(
            self._converter.convert(markdown, thinking=None)
        )
        try:
            await self._bot.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(markdown=rich_markdown),
                message_thread_id=message_thread_id,
            )
        except (AiogramError, ValueError) as exc:
            logger.warning("rich send failed; falling back to plain: %s", exc)
            return False
        return True

    async def _send_plain(
        self, chat_id: int, text: str, message_thread_id: int | None
    ) -> None:
        """Send ``text`` as plain message(s), splitting on the length limit."""
        for chunk in _split_for_length(text):
            await self._bot.send_message(
                chat_id=chat_id, text=chunk, message_thread_id=message_thread_id
            )


def _reply_to_sender_id(message: MessageLike) -> int | None:
    """The from-user id of the message ``message`` replies to (``None`` if not a reply).

    Forum-topic guard (BOB-027): in a Telegram forum topic EVERY message carries an
    *implicit* ``reply_to_message`` pointing at the topic's root message — whose
    ``message_id`` equals the message's ``message_thread_id``. That is NOT a real reply
    (the user did not reply to anyone), so it is ignored; only a reply to a DIFFERENT
    message counts. Without this, every message in Bob's topic looks like a reply to the
    topic creator (the owner), and addressivity (BOB-023) misreads the whole topic as
    "directed to someone else" → Bob stays silent unless explicitly named.
    """
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return None
    thread_id = message.message_thread_id
    if thread_id is not None and getattr(replied, "message_id", None) == thread_id:
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


def is_reaction_update(update: UpdateLike) -> bool:
    """Whether ``update`` carries a reaction change (per-user or anonymous count)."""
    return _reaction_of(update) is not None or _reaction_count_of(update) is not None


def _reaction_of(update: UpdateLike) -> MessageReactionUpdatedLike | None:
    """The per-user ``message_reaction`` payload of ``update``, if present (BOB-050).

    Read defensively via ``getattr`` so update views that predate reactions (and
    the many test fakes) need not carry the attribute — they simply have no
    reaction.
    """
    reaction: MessageReactionUpdatedLike | None = getattr(
        update, "message_reaction", None
    )
    return reaction


def _reaction_count_of(
    update: UpdateLike,
) -> MessageReactionCountUpdatedLike | None:
    """The anonymous ``message_reaction_count`` payload of ``update``, if present."""
    count: MessageReactionCountUpdatedLike | None = getattr(
        update, "message_reaction_count", None
    )
    return count


def _reaction_diff(
    old_reaction: Sequence[object], new_reaction: Sequence[object]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Diff a reactor's old → new reaction lists into (added, removed) emoji."""
    old_emojis = _reaction_emojis(old_reaction)
    new_emojis = _reaction_emojis(new_reaction)
    added = tuple(emoji for emoji in new_emojis if emoji not in old_emojis)
    removed = tuple(emoji for emoji in old_emojis if emoji not in new_emojis)
    return added, removed


def _reaction_emojis(reactions: Sequence[object]) -> tuple[str, ...]:
    """The standard emoji of each reaction item (non-emoji items are skipped)."""
    return tuple(
        emoji
        for reaction in reactions
        if isinstance(emoji := getattr(reaction, "emoji", None), str)
    )


def _count_emojis(reactions: Sequence[object]) -> tuple[str, ...]:
    """The emoji of each ``ReactionCount`` item (its ``type`` carries the emoji)."""
    return tuple(
        emoji
        for reaction in reactions
        if isinstance(
            emoji := getattr(getattr(reaction, "type", None), "emoji", None), str
        )
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
