# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for BOB-050 .1 — reaction intake (perceiving reactions on Bob's messages).

The gateway turns a Telegram ``message_reaction`` update into a
:class:`BobMessageReaction` event — but only for reactions on Bob's OWN messages
(filtered by the recorded outgoing message_id). A per-user update yields the
added/removed-emoji diff + the reactor's identity; an anonymous
``message_reaction_count`` yields the defensive "someone reacted" signal
(``reactor_sender_id=None``). A reaction on a non-Bob message is dropped. No real
network: hand-rolled fakes for the update payloads and the Bob-message filter.
"""
# ruff: noqa: ARG002 — BotLike fake methods accept the protocol args but ignore them.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import (
    BOB_MESSAGE_REACTION,
    BobMessageReaction,
)
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.infrastructure.telegram.gateway import MessageLike, UpdateLike
    from bob.kernel.ports import DomainEvent


# --- Reaction-update fakes ----------------------------------------------------


@dataclass
class _FakeEmoji:
    """A standard reaction (``ReactionTypeEmoji``-shaped: carries ``emoji``)."""

    emoji: str


@dataclass
class _FakeChat:
    id: int


@dataclass
class _FakeUser:
    id: int
    full_name: str


@dataclass
class _FakeReactionCount:
    """A ``ReactionCount``-shaped item: a ``type`` carrying the emoji + a total."""

    type: _FakeEmoji
    total_count: int


@dataclass
class _FakeMessageReaction:
    """A ``MessageReactionUpdated``-shaped payload."""

    chat: _FakeChat
    message_id: int
    old_reaction: list[_FakeEmoji]
    new_reaction: list[_FakeEmoji]
    user: _FakeUser | None = None


@dataclass
class _FakeReactionCountUpdated:
    """A ``MessageReactionCountUpdated``-shaped payload (anonymous, no user)."""

    chat: _FakeChat
    message_id: int
    reactions: list[_FakeReactionCount]


@dataclass
class _FakeReactionUpdate:
    """An :class:`UpdateLike` carrying a reaction payload (no ordinary message)."""

    update_id: int
    message_reaction: _FakeMessageReaction | None = None
    message_reaction_count: _FakeReactionCountUpdated | None = None
    message: MessageLike | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


@dataclass
class _FakeFilter:
    """Records the looked-up id; answers ``True`` for the known Bob message_id."""

    bob_message_ids: set[int] = field(default_factory=set)
    lookups: list[int] = field(default_factory=list)

    async def is_bob_message(self, message_id: int) -> bool:
        self.lookups.append(message_id)
        return message_id in self.bob_message_ids


@dataclass
class _FakeBot:
    """A minimal BotLike whose intake serves no updates (reactions are fed directly)."""

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike:
        raise NotImplementedError  # pragma: no cover

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        return True

    async def send_rich_message(
        self, *, chat_id: int, rich_message: object, message_thread_id: int | None = None
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
        raise NotImplementedError  # pragma: no cover


async def _noop_sleep(_seconds: float) -> None:
    return None


def _gateway(*, filter_: _FakeFilter | None) -> tuple[TelegramGateway, list[DomainEvent]]:
    bus = AsyncEventBus()
    captured: list[DomainEvent] = []

    async def _handler(event: DomainEvent) -> None:
        captured.append(event)

    bus.subscribe(BOB_MESSAGE_REACTION, _handler)
    gateway = TelegramGateway(
        bot=_FakeBot(),
        bus=bus,
        poll_timeout=10,
        typing_interval=4.0,
        clock=lambda: 0.0,
        sleep=_noop_sleep,
        bob_reaction_filter=filter_,
    )
    return gateway, captured


# --- Per-user reaction: add ---------------------------------------------------


@pytest.mark.asyncio
async def test_added_reaction_on_bob_message_publishes_event() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=1,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=42,
            old_reaction=[],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    published = await gateway.intake_reaction(update)

    assert published is True
    assert len(captured) == 1
    event = captured[0]
    assert isinstance(event, BobMessageReaction)
    assert event.chat_id == 100
    assert event.message_id == 42
    assert event.emoji_added == ("❤️",)
    assert event.emoji_removed == ()
    assert event.reactor_sender_id == 777
    assert event.reactor_name == "Ada"


# --- Per-user reaction: remove ------------------------------------------------


@pytest.mark.asyncio
async def test_removed_reaction_on_bob_message_publishes_removed() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=2,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=42,
            old_reaction=[_FakeEmoji("❤️")],
            new_reaction=[],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    published = await gateway.intake_reaction(update)

    assert published is True
    event = captured[0]
    assert isinstance(event, BobMessageReaction)
    assert event.emoji_added == ()
    assert event.emoji_removed == ("❤️",)


# --- Anonymous count-only -----------------------------------------------------


@pytest.mark.asyncio
async def test_anonymous_count_update_publishes_without_reactor() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=3,
        message_reaction_count=_FakeReactionCountUpdated(
            chat=_FakeChat(id=100),
            message_id=42,
            reactions=[_FakeReactionCount(type=_FakeEmoji("🔥"), total_count=2)],
        ),
    )

    published = await gateway.intake_reaction(update)

    assert published is True
    event = captured[0]
    assert isinstance(event, BobMessageReaction)
    assert event.emoji_added == ("🔥",)
    assert event.reactor_sender_id is None
    assert event.reactor_name is None


# --- Filter: not Bob's message ------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_on_non_bob_message_is_filtered() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=4,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=999,  # not a recorded Bob message
            old_reaction=[],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    published = await gateway.intake_reaction(update)

    assert published is False
    assert captured == []
    assert filter_.lookups == [999]


@pytest.mark.asyncio
async def test_reaction_without_filter_is_dropped() -> None:
    gateway, captured = _gateway(filter_=None)
    update = _FakeReactionUpdate(
        update_id=5,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=42,
            old_reaction=[],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    assert await gateway.intake_reaction(update) is False
    assert captured == []


# --- No net change / dedup ----------------------------------------------------


@pytest.mark.asyncio
async def test_no_emoji_change_publishes_nothing() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=6,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=42,
            old_reaction=[_FakeEmoji("❤️")],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    assert await gateway.intake_reaction(update) is False
    assert captured == []


@pytest.mark.asyncio
async def test_duplicate_reaction_update_id_is_deduplicated() -> None:
    filter_ = _FakeFilter(bob_message_ids={42})
    gateway, captured = _gateway(filter_=filter_)
    update = _FakeReactionUpdate(
        update_id=7,
        message_reaction=_FakeMessageReaction(
            chat=_FakeChat(id=100),
            message_id=42,
            old_reaction=[],
            new_reaction=[_FakeEmoji("❤️")],
            user=_FakeUser(id=777, full_name="Ada"),
        ),
    )

    assert await gateway.intake_reaction(update) is True
    assert await gateway.intake_reaction(update) is False
    assert len(captured) == 1
