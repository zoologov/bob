# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Routing-by-content regression for the multi-bot router (BOB-005).

The live bug: GUPPI replied but **Bob was silent** in his topic. Both admin bots
see a group message, so each delivers its own copy; cross-bot dedup keyed on
``(chat_id, message_id)`` keeps exactly one. When the **GUPPI-delivered** copy
won the dedup, routing was effectively coupled to the delivering bot — the
surviving copy was handled in the GUPPI context (a no-op for an authorized,
non-command message) and swallowed, while the Bob-delivered copy that *would*
have triggered Bob's pipeline was dropped as the cross-bot duplicate.

These tests pin the fix: after dedup, the **single surviving copy is routed by
its CONTENT** (chat + topic + authz), independent of which bot delivered it —
so a Bob-topic message reaches Bob's pipeline exactly once whichever bot's copy
arrived first, and the reply still goes via the Bob bot.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.guppi import GUPPI_REJECT_TEXT
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.domain import ports

_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732
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


@dataclass
class _FakeChat:
    id: int


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
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
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
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not exercised here
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
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


@dataclass
class _AllowAuthorizer:
    """Authorizes everyone; owner check by id."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:
        return True

    async def authorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError


@dataclass
class _DenyAuthorizer:
    """Denies everyone (owner check by id)."""

    def is_owner(self, user_id: int | None) -> bool:  # noqa: ARG002
        return False

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:
        return False

    async def authorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover - unused
        raise NotImplementedError


def _bob_topic_update(
    update_id: int,
    *,
    message_id: int = 41,
    text: str | None = "hi Bob",
    chat_id: int = _CHAT_ID,
    thread_id: int | None = _BOB_TOPIC_ID,
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(
            message_id=message_id, text=text, message_thread_id=thread_id
        ),
        effective_chat=_FakeChat(id=chat_id),
        effective_user=_FakeUser(id=user_id),
    )


def _build(
    bob: _FakeBot,
    guppi: _FakeBot,
    *,
    authorizer: _AllowAuthorizer | _DenyAuthorizer,
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
        registry=registry, bus=bus, poll_timeout=10, authorizer=authorizer
    )
    return gateway, bus


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


# --- The failing live case: GUPPI delivers first ------------------------------


@pytest.mark.asyncio
async def test_bob_topic_message_delivered_first_via_guppi_reaches_bob_once() -> None:
    """GUPPI's copy wins the cross-bot dedup; Bob's pipeline still fires once.

    This is the exact live failure: the GUPPI-delivered copy of an authorized
    Bob-topic message arrives first (wins dedup), Bob's copy is dropped as the
    cross-bot duplicate — yet routing by content must still publish to Bob's
    pipeline exactly once.
    """
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, authorizer=_AllowAuthorizer())
    received = await _collect(bus)

    # GUPPI's copy arrives first (distinct update_ids, same chat+message_id).
    first = await gateway.route(_bob_topic_update(200, message_id=41), BotIdentity.GUPPI)
    # Bob's copy of the same message arrives second.
    second = await gateway.route(_bob_topic_update(100, message_id=41), BotIdentity.BOB)

    assert first is True  # routed to Bob's pipeline by content, not by bot
    assert second is False  # cross-bot duplicate, dropped
    assert len(received) == 1
    assert received[0].text == "hi Bob"
    # GUPPI must not have spoken (it is not a reject / owner command).
    assert guppi.sends == []


@pytest.mark.asyncio
async def test_bob_topic_message_delivered_first_via_guppi_through_poll() -> None:
    """Same as above but through the real poll loop across two poll cycles."""
    bob, guppi = _FakeBot(), _FakeBot()
    # GUPPI sees the message in poll cycle 1; Bob sees its copy in cycle 2.
    guppi.updates_batches = [[_bob_topic_update(200, message_id=41)], []]
    bob.updates_batches = [[], [_bob_topic_update(100, message_id=41)]]
    gateway, bus = _build(bob, guppi, authorizer=_AllowAuthorizer())
    received = await _collect(bus)

    await gateway.poll_once()  # cycle 1: GUPPI delivers
    await gateway.poll_once()  # cycle 2: Bob delivers the duplicate

    assert len(received) == 1
    assert guppi.sends == []


@pytest.mark.asyncio
async def test_guppi_copy_without_thread_id_still_routes_to_bob() -> None:
    """The GUPPI-delivered copy may lack the topic thread_id; Bob's copy carries it.

    In the live forum, the General-scoped GUPPI bot's copy of a Bob-topic message
    can arrive WITHOUT ``message_thread_id`` while the Bob bot's copy carries it.
    Routing must use the content of whichever copy identifies the topic, so the
    message still reaches Bob's pipeline exactly once (and GUPPI stays silent).
    """
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, authorizer=_AllowAuthorizer())
    received = await _collect(bus)

    # GUPPI's copy arrives first WITHOUT the topic thread (General-scoped bot).
    first = await gateway.route(
        _bob_topic_update(200, message_id=41, thread_id=None), BotIdentity.GUPPI
    )
    # Bob's copy of the same message carries the topic thread.
    second = await gateway.route(
        _bob_topic_update(100, message_id=41, thread_id=_BOB_TOPIC_ID),
        BotIdentity.BOB,
    )

    assert len(received) == 1
    assert (first, second).count(True) == 1  # published exactly once
    assert guppi.sends == []  # not a reject / owner command → GUPPI silent


@pytest.mark.asyncio
async def test_bob_topic_message_delivered_first_via_bob_reaches_bob_once() -> None:
    """Delivered first via the Bob bot → still exactly once (no regression)."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, authorizer=_AllowAuthorizer())
    received = await _collect(bus)

    first = await gateway.route(_bob_topic_update(100, message_id=41), BotIdentity.BOB)
    second = await gateway.route(
        _bob_topic_update(200, message_id=41), BotIdentity.GUPPI
    )

    assert first is True
    assert second is False
    assert len(received) == 1


@pytest.mark.asyncio
async def test_bob_reply_goes_via_the_bob_bot() -> None:
    """The reply still uses the Bob bot's identity, pinned to his topic thread."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, _ = _build(bob, guppi, authorizer=_AllowAuthorizer())
    reply_gateway = gateway.reply_gateway(BotIdentity.BOB)

    async with reply_gateway.typing_indicator(chat_id=_CHAT_ID):
        await asyncio.sleep(0)
    await reply_gateway.reply(chat_id=_CHAT_ID, markdown="hello")

    assert bob.sends, "Bob's bot should have delivered the reply"
    assert all(call.message_thread_id == _BOB_TOPIC_ID for call in bob.sends)
    assert guppi.sends == []  # GUPPI never sends Bob's reply


# --- Unchanged GUPPI branches (no regression) ---------------------------------


@pytest.mark.asyncio
async def test_owner_command_in_general_still_handled_by_guppi() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, authorizer=_AllowAuthorizer())
    received = await _collect(bus)

    published = await gateway.route(
        _bob_topic_update(
            30, message_id=50, text="/status", thread_id=None, user_id=_OWNER_ID
        ),
        BotIdentity.GUPPI,
    )

    assert published is False
    assert received == []
    assert bob.sends == []
    assert len(guppi.sends) == 1  # GUPPI answers /status


@pytest.mark.asyncio
async def test_unauthorized_in_bob_topic_still_rejected_by_guppi() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(bob, guppi, authorizer=_DenyAuthorizer())
    received = await _collect(bus)

    published = await gateway.route(
        _bob_topic_update(31, message_id=51, user_id=_STRANGER_ID),
        BotIdentity.GUPPI,
    )

    assert published is False
    assert received == []
    assert bob.sends == []  # Bob's pipeline NOT invoked
    assert len(guppi.sends) == 1
    assert guppi.sends[0].text == GUPPI_REJECT_TEXT
    assert guppi.sends[0].message_thread_id == _BOB_TOPIC_ID
