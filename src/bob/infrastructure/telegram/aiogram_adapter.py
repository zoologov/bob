# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""aiogram bot adapter — the concrete Telegram edge behind the gateway's ``BotLike``.

Adapts aiogram's async ``Bot`` (intake ``get_updates`` normalisation + the reply /
reaction / diagram send surface) into the gateway's structural
:class:`~bob.infrastructure.telegram.gateway.BotLike`, lifts each aiogram ``Update``'s
nested chat/sender into the flat :class:`UpdateLike` the gateway reads, and builds the
real bot from its configured (env) token. Also holds the :class:`_BobReactionFilter`,
the episodic-store realisation of the gateway's ``BobMessageFilter`` (a reaction is
published only when it lands on one of Bob's own messages). Extracted verbatim from the
composition root (BOB-062.7a); the composition root injects these seams so the whole
graph runs on fakes without a network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.infrastructure.telegram.gateway import ALLOWED_UPDATES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from aiogram.types import BufferedInputFile, InputRichMessage, ReactionTypeEmoji

    from bob.infrastructure.telegram.gateway import (
        BotLike,
        BotUserLike,
        MessageLike,
        UpdateLike,
    )
    from bob.memory.adapters import SqliteMemoryRepo


class _BobReactionFilter:
    """Tell whether a reacted-to ``message_id`` is one of Bob's own messages (BOB-050).

    Realises :class:`~bob.infrastructure.telegram.gateway.BobMessageFilter` over the
    episodic store: a reaction is published only when the ``message_id`` it was placed
    on matches an episode that recorded it as Bob's outgoing reply. No match (an old /
    non-Bob message) → the reaction is dropped gracefully.
    """

    def __init__(self, repo: SqliteMemoryRepo) -> None:
        self._repo = repo

    async def is_bob_message(self, message_id: int) -> bool:
        episode = await self._repo.episode_by_bob_message_id(message_id)
        return episode is not None


@dataclass(frozen=True)
class _ChatView:
    """An :class:`UpdateLike` chat view over an aiogram ``Update``."""

    id: int


@dataclass(frozen=True)
class _UserView:
    """An :class:`UpdateLike` user view over an aiogram ``Update``."""

    id: int
    full_name: str


@dataclass(frozen=True)
class _UpdateView:
    """Adapt an aiogram ``Update`` to the gateway's :class:`UpdateLike`.

    aiogram nests chat/sender under ``message``; the gateway reads them as the
    flat ``effective_chat`` / ``effective_user`` accessors, so this view lifts them
    up while leaving the underlying aiogram message as the message.

    A reaction update (BOB-050) carries no ``message``; the raw aiogram
    ``message_reaction`` / ``message_reaction_count`` payloads are passed through
    unchanged for the gateway's reaction route to read structurally.
    """

    update_id: int
    message: MessageLike | None
    effective_chat: _ChatView | None
    effective_user: _UserView | None
    message_reaction: object | None = None
    message_reaction_count: object | None = None


class _AiogramBotAdapter:
    """Adapt aiogram's async ``Bot`` to the gateway's :class:`BotLike`.

    Intake calls ``get_updates`` and normalises each aiogram ``Update`` into an
    :class:`UpdateLike`; the reply path (BOB-008, Variant A) shows a "typing…"
    indicator via ``send_chat_action`` while it assembles the reply, then commits
    the finished reply with ``send_rich_message`` (degrading to ``send_message`` on
    a rich error).
    """

    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def get_me(self) -> BotUserLike:
        # Bob's own bot identity (id + @username), resolved once at startup so the
        # addressivity scan (BOB-023) can tell a mention of Bob from one of others.
        return await self._bot.get_me()  # type: ignore[attr-defined,no-any-return]

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]:
        # BOB-050: request reaction updates explicitly — ``message_reaction`` /
        # ``message_reaction_count`` are NOT in Telegram's default allowed set, so
        # without this they are never delivered. ``message`` keeps ordinary intake.
        updates = await self._bot.get_updates(  # type: ignore[attr-defined]
            offset=offset, timeout=timeout, allowed_updates=list(ALLOWED_UPDATES)
        )
        return [_to_update_view(update) for update in updates]

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike:
        return await self._bot.send_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, text=text, message_thread_id=message_thread_id
        )

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        return await self._bot.send_chat_action(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, action=action, message_thread_id=message_thread_id
        )

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        return await self._bot.send_rich_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            rich_message=rich_message,
            message_thread_id=message_thread_id,
        )

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> object:
        # BOB-046 .2: edit the coding-session status panel in place (one message edited
        # through the phases, not a stream of new messages).
        return await self._bot.edit_message_text(  # type: ignore[attr-defined]
            chat_id=chat_id, message_id=message_id, text=text
        )

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[ReactionTypeEmoji],
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # Telegram's ``setMessageReaction`` targets the message directly (no thread
        # arg); ``message_thread_id`` is accepted for BotLike parity and dropped.
        return await self._bot.set_message_reaction(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, message_id=message_id, reaction=list(reaction)
        )

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        # BOB-035: post a rendered diagram PNG (already wrapped as a BufferedInputFile
        # by the gateway) as a native Telegram photo, pinned to the bot's thread.
        return await self._bot.send_photo(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            message_thread_id=message_thread_id,
        )

    async def send_document(
        self,
        *,
        chat_id: int,
        document: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        # BOB-037: post a rendered diagram as an UNCOMPRESSED document (already wrapped
        # as a BufferedInputFile by the gateway) so Telegram does not recompress it —
        # full resolution, pinned to the bot's thread.
        return await self._bot.send_document(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            document=document,
            caption=caption,
            message_thread_id=message_thread_id,
        )


def _to_update_view(update: object) -> _UpdateView:
    """Lift an aiogram ``Update``'s nested chat/sender into an :class:`UpdateLike`."""
    message: MessageLike | None = getattr(update, "message", None)
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    return _UpdateView(
        update_id=update.update_id,  # type: ignore[attr-defined]
        message=message,
        effective_chat=_ChatView(id=chat.id) if chat is not None else None,
        effective_user=(
            _UserView(id=user.id, full_name=user.full_name) if user is not None else None
        ),
        message_reaction=getattr(update, "message_reaction", None),
        message_reaction_count=getattr(update, "message_reaction_count", None),
    )


def _build_real_bot(bot_section: Mapping[str, object], identity: str) -> BotLike:
    """Construct a real aiogram ``Bot`` from a bot's configured (env) token.

    ``identity`` (``"bob"`` / ``"guppi"``) only names the missing token in the
    error — the token itself comes from env (``BOB_TELEGRAM__TOKEN`` /
    ``GUPPI_TELEGRAM__TOKEN``), never inlined.
    """
    from aiogram import Bot  # noqa: PLC0415 — lazy: only the real-bot path needs aiogram

    token = bot_section.get("token")
    if not isinstance(token, str) or not token:
        raise KeyError(
            f"telegram.{identity}.token is required to build the real {identity} bot"
        )
    return _AiogramBotAdapter(Bot(token=token))
