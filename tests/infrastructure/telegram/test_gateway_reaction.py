# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Telegram reactor — native ``set_message_reaction`` + fallback (BOB-018).

On a react-only turn the gateway sets a single native emoji reaction on the user's
message instead of composing a reply. The reaction is **best-effort**: on any
transport error it degrades to a brief textual ack (so the user still gets a sign
of life) and never raises into the caller. No real Telegram network: a hand-rolled
fake aiogram-style bot records the ``set_message_reaction`` / ``send_message`` calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.infrastructure.telegram.gateway import MessageLike, UpdateLike


@dataclass
class _FakeMessage:
    """A minimal Telegram message satisfying ``MessageLike`` (return value)."""

    message_id: int = 0
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _ReactionCall:
    chat_id: int
    message_id: int
    emoji: tuple[str, ...]
    message_thread_id: int | None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records reaction/send calls; can be scripted to fail the reaction."""

    reactions: list[_ReactionCall] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    reaction_raises: bool = False

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> MessageLike:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return _FakeMessage()

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: object, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> MessageLike:
        return _FakeMessage()

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[object],
        message_thread_id: int | None = None,
    ) -> bool:
        if self.reaction_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="reaction not allowed",
            )
        emoji = tuple(getattr(r, "emoji", "") for r in reaction)
        self.reactions.append(
            _ReactionCall(
                chat_id=chat_id,
                message_id=message_id,
                emoji=emoji,
                message_thread_id=message_thread_id,
            )
        )
        return True


async def _noop_sleep(_seconds: float) -> None:
    return None


def _gateway(bot: _FakeBot, *, reply_thread_id: int | None = None) -> TelegramGateway:
    return TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        typing_interval=4.0,
        clock=lambda: 0.0,
        sleep=_noop_sleep,
        reply_thread_id=reply_thread_id,
    )


@pytest.mark.asyncio
async def test_react_sets_a_native_reaction_pinned_to_the_thread() -> None:
    bot = _FakeBot()
    gateway = _gateway(bot, reply_thread_id=42)

    await gateway.react(chat_id=555, message_id=10, emoji="🔥")

    assert len(bot.reactions) == 1
    call = bot.reactions[0]
    assert call.chat_id == 555
    assert call.message_id == 10
    assert call.emoji == ("🔥",)
    assert call.message_thread_id == 42
    # A successful reaction sends no text fallback.
    assert bot.sends == []


@pytest.mark.asyncio
async def test_react_falls_back_to_a_brief_ack_on_api_error() -> None:
    # Best-effort: a rejected reaction degrades to a short textual ack — the user
    # still gets a sign of life — and never raises into the caller.
    bot = _FakeBot(reaction_raises=True)
    gateway = _gateway(bot, reply_thread_id=42)

    await gateway.react(chat_id=555, message_id=10, emoji="🔥")

    assert bot.reactions == []
    assert len(bot.sends) == 1
    ack = bot.sends[0]
    assert ack.chat_id == 555
    assert ack.text.strip() != ""
    assert ack.message_thread_id == 42
