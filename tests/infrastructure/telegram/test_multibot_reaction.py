# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-050 .1 — reaction routing through the multi-bot gateway.

A reaction update is dispatched to Bob's inner gateway (only via Bob's OWN bot
copy, to avoid a double from GUPPI), filtered to Bob's messages, and published as
a :class:`BobMessageReaction`. It never counts as a published
:class:`MessageReceived`. Fake aiogram-shaped bots/updates; no network.
"""
# ruff: noqa: ARG002 — BotLike fake methods accept the protocol args but ignore them.

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import BOB_MESSAGE_REACTION, BobMessageReaction
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.infrastructure.telegram.gateway import MessageLike
    from bob.kernel import ports

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32


@dataclass
class _FakeEmoji:
    emoji: str


@dataclass
class _FakeChat:
    id: int
    type: str = "supergroup"


@dataclass
class _FakeUser:
    id: int
    full_name: str = "Ada"


@dataclass
class _FakeMessageReaction:
    chat: _FakeChat
    message_id: int
    old_reaction: list[_FakeEmoji]
    new_reaction: list[_FakeEmoji]
    user: _FakeUser | None = None


@dataclass
class _FakeUpdate:
    update_id: int
    message: MessageLike | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None
    message_reaction: _FakeMessageReaction | None = None
    message_reaction_count: object | None = None


@dataclass
class _FakeBot:
    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[_FakeUpdate]:
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> MessageLike:
        raise NotImplementedError  # pragma: no cover

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: object, message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> MessageLike:
        raise NotImplementedError  # pragma: no cover

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        raise NotImplementedError  # pragma: no cover

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        raise NotImplementedError  # pragma: no cover

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[object],
        message_thread_id: int | None = None,
    ) -> bool:
        return True


@dataclass
class _FakeFilter:
    bob_message_ids: set[int] = field(default_factory=set)

    async def is_bob_message(self, message_id: int) -> bool:
        return message_id in self.bob_message_ids


async def _noop_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


def _build(
    bots: dict[BotIdentity, _FakeBot], *, filter_: _FakeFilter
) -> tuple[MultiBotGateway, list[BobMessageReaction]]:
    bus = AsyncEventBus()
    captured: list[BobMessageReaction] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, BobMessageReaction)
        captured.append(event)

    bus.subscribe(BOB_MESSAGE_REACTION, handler)

    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bots[BotIdentity.BOB],
        scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=bots[BotIdentity.GUPPI],
        scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
    )
    gateway = MultiBotGateway(
        registry=registry,
        bus=bus,
        poll_timeout=10,
        reply_typing_interval=4.0,
        reply_clock=lambda: 0.0,
        reply_sleep=_noop_sleep,
        bob_reaction_filter=filter_,
    )
    return gateway, captured


def _reaction_update(update_id: int, *, message_id: int) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=_CHAT_ID),
            message_id=message_id,
            old_reaction=[],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777),
        ),
    )


@pytest.mark.asyncio
async def test_reaction_via_bob_bot_is_published() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_reaction_update(10, message_id=42)]]
    gateway, captured = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        filter_=_FakeFilter(bob_message_ids={42}),
    )

    published = await gateway.poll_once()

    # A reaction is not a MessageReceived, so it is not counted as published.
    assert published == 0
    assert len(captured) == 1
    assert captured[0].message_id == 42
    assert captured[0].emoji_added == ("❤️",)


@pytest.mark.asyncio
async def test_reaction_via_guppi_bot_is_ignored() -> None:
    # GUPPI's copy of a reaction is ignored — only Bob's own bot routes reactions,
    # so the event is not double-published.
    bob, guppi = _FakeBot(), _FakeBot()
    guppi.updates_batches = [[_reaction_update(11, message_id=42)]]
    gateway, captured = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        filter_=_FakeFilter(bob_message_ids={42}),
    )

    await gateway.poll_once()

    assert captured == []


@pytest.mark.asyncio
async def test_reaction_on_non_bob_message_is_filtered() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_reaction_update(12, message_id=999)]]
    gateway, captured = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        filter_=_FakeFilter(bob_message_ids={42}),
    )

    await gateway.poll_once()

    assert captured == []
