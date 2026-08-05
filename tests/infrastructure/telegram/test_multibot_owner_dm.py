# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Owner-DM routing + DM reply-threading for the multi-bot router (BOB-083.1).

The live bug (recon): an inbound private DM from the owner was DROPPED at
:meth:`MultiBotGateway._route_by_content` — the owner's 1:1 DM ``chat_id``
(== owner ``user_id``) matched neither Bob's group-topic scope nor the General
chat, so it fell to ``UNROUTABLE`` and was silently dropped BEFORE the authz
gate (BOB-082 had already authorized owner-DM at ``is_authorized``, but the
router never reached intake). Even if routed, Bob's reply is pinned to his group
topic thread, so a DM turn's reply would land in the group, not the DM.

These tests pin the fix (INV-0):

* the OWNER's own DM (private, ``chat_id == owner_dm_chat_id``, owner sender) is
  routed onto Bob's pipeline exactly like a Bob-topic message;
* a stranger DM / foreign chat_id / non-owner sender is STILL dropped
  (``UNROUTABLE``) — only the owner's own DM is newly routed;
* when the owner-DM is not configured, behaviour is unchanged (DM dropped);
* a DM turn's reply targets the DM (``message_thread_id=None``) while a group
  turn's reply stays pinned to Bob's topic (byte-identical).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.kernel import ports

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
_OWNER_DM_CHAT_ID = _OWNER_ID  # a 1:1 DM chat.id equals the user's id
_STRANGER_ID = 555


# --- Test doubles -------------------------------------------------------------


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str = "Owner"
    username: str | None = None


@dataclass
class _FakeChat:
    id: int
    type: str = "supergroup"


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str | None
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records sends; serves scripted update batches (no network)."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    next_message_id: int = 900

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

    async def send_chat_action(
        self,
        *,
        chat_id: int,
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,
    ) -> bool:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=None, message_thread_id=message_thread_id)
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(
                chat_id=chat_id,
                text=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=rich_message.markdown)
        self.next_message_id += 1
        return msg

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not exercised here
        return True

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:  # pragma: no cover - not exercised here
        raise NotImplementedError


@dataclass
class _DmAuthorizer:
    """Mirrors BOB-082: owner is authorized in his own DM; strangers are not.

    ``is_authorized`` admits the owner in the owner-DM chat (and Bob's allowed
    group), matching the real :class:`Authorizer`. ``is_owner`` is the strict
    owner-identity check the router's DM branch guards on.
    """

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(self, *, user_id: int | None, chat_id: int) -> bool:
        if user_id == _OWNER_ID and chat_id == _OWNER_DM_CHAT_ID:
            return True
        return user_id == _OWNER_ID and chat_id == _CHAT_ID

    async def authorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError


def _owner_dm_update(
    update_id: int,
    *,
    message_id: int = 80,
    text: str | None = "привет, Боб",
    chat_id: int = _OWNER_DM_CHAT_ID,
    chat_type: str = "private",
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(message_id=message_id, text=text, message_thread_id=None),
        effective_chat=_FakeChat(id=chat_id, type=chat_type),
        effective_user=_FakeUser(id=user_id),
    )


def _bob_topic_update(
    update_id: int,
    *,
    message_id: int = 41,
    text: str | None = "hi Bob",
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(
            message_id=message_id, text=text, message_thread_id=_BOB_TOPIC_ID
        ),
        effective_chat=_FakeChat(id=_CHAT_ID),
        effective_user=_FakeUser(id=user_id),
    )


def _build(
    bob: _FakeBot,
    guppi: _FakeBot,
    *,
    owner_dm_chat_id: int | None = None,
) -> tuple[MultiBotGateway, AsyncEventBus]:
    bus = AsyncEventBus()
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=guppi,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
    )
    gateway = MultiBotGateway(
        registry=registry,
        bus=bus,
        poll_timeout=10,
        authorizer=_DmAuthorizer(),
        owner_dm_chat_id=owner_dm_chat_id,
    )
    return gateway, bus


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


# --- Inbound owner-DM routing (INV-0) -----------------------------------------


@pytest.mark.asyncio
async def test_owner_dm_reaches_bob_pipeline() -> None:
    """The owner's own private DM is routed onto Bob's pipeline (published once)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(_owner_dm_update(100), BotIdentity.BOB)

    assert published is True
    assert len(received) == 1
    assert received[0].text == "привет, Боб"
    assert received[0].is_group is False  # a private DM is not a group turn
    assert guppi.sends == []  # GUPPI stays silent


@pytest.mark.asyncio
async def test_owner_dm_code_command_reaches_pipeline() -> None:
    """A ``/code`` from the owner's DM is not consumed by the router (unblocks S0)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(
        _owner_dm_update(101, message_id=81, text="/code fix the bug"),
        BotIdentity.BOB,
    )

    assert published is True
    assert len(received) == 1
    assert received[0].text == "/code fix the bug"


@pytest.mark.asyncio
async def test_stranger_dm_still_dropped() -> None:
    """A stranger's DM (different chat_id, non-owner sender) is dropped (UNROUTABLE)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(
        _owner_dm_update(102, chat_id=_STRANGER_ID, user_id=_STRANGER_ID),
        BotIdentity.BOB,
    )

    assert published is False
    assert received == []
    assert bob.sends == []
    assert guppi.sends == []  # silent — no reveal


@pytest.mark.asyncio
async def test_non_owner_sender_in_owner_dm_chat_dropped() -> None:
    """Only the OWNER's own DM routes: a non-owner sender is dropped (defensive)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(
        _owner_dm_update(103, user_id=_STRANGER_ID),
        BotIdentity.BOB,
    )

    assert published is False
    assert received == []
    assert bob.sends == []


@pytest.mark.asyncio
async def test_non_private_chat_at_owner_dm_id_not_dm_routed() -> None:
    """A non-private chat is never treated as the owner DM (guard on chat.type)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(
        _owner_dm_update(104, chat_type="group"),
        BotIdentity.BOB,
    )

    assert published is False
    assert received == []


@pytest.mark.asyncio
async def test_owner_dm_dropped_when_not_configured() -> None:
    """With no owner-DM configured, an owner DM is dropped — behaviour unchanged."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi)  # owner_dm_chat_id defaults to None
    received = await _collect(bus)

    published = await gateway.route(_owner_dm_update(105), BotIdentity.BOB)

    assert published is False
    assert received == []
    assert bob.sends == []


@pytest.mark.asyncio
async def test_group_topic_message_unchanged_with_dm_configured() -> None:
    """The group path is unchanged when the owner-DM is configured (no regression)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    received = await _collect(bus)

    published = await gateway.route(_bob_topic_update(106), BotIdentity.BOB)

    assert published is True
    assert len(received) == 1
    assert received[0].is_group is True
    assert guppi.sends == []


# --- DM reply threading (reply lands in the DM, not the group) ----------------


@pytest.mark.asyncio
async def test_owner_dm_reply_is_unthreaded() -> None:
    """A DM turn's reply targets the DM chat with ``message_thread_id=None``."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, _ = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    reply_gateway = gateway.reply_gateway(BotIdentity.BOB)

    async with reply_gateway.typing_indicator(chat_id=_OWNER_DM_CHAT_ID):
        await asyncio.sleep(0)
    await reply_gateway.reply(chat_id=_OWNER_DM_CHAT_ID, markdown="готово")

    assert bob.sends, "Bob's bot should have delivered the DM reply"
    assert all(call.chat_id == _OWNER_DM_CHAT_ID for call in bob.sends)
    assert all(call.message_thread_id is None for call in bob.sends)
    assert guppi.sends == []


@pytest.mark.asyncio
async def test_group_reply_still_pinned_to_topic_with_dm_configured() -> None:
    """A group turn's reply stays pinned to Bob's topic even with a DM configured."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, _ = _build(bob, guppi, owner_dm_chat_id=_OWNER_DM_CHAT_ID)
    reply_gateway = gateway.reply_gateway(BotIdentity.BOB)

    async with reply_gateway.typing_indicator(chat_id=_CHAT_ID):
        await asyncio.sleep(0)
    await reply_gateway.reply(chat_id=_CHAT_ID, markdown="hello")

    assert bob.sends, "Bob's bot should have delivered the group reply"
    assert all(call.message_thread_id == _BOB_TOPIC_ID for call in bob.sends)
    assert guppi.sends == []
