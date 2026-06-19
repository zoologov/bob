# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Edge-case hardening for the multi-bot router (BOB-003 BEAD-05).

The happy paths and the four user stories are covered by ``test_multibot.py``,
``test_multibot_guppi.py`` and ``test_e2e_two_bot.py``. This module closes the
remaining *defensive* branches of :class:`MultiBotGateway`, all reachable with
fake bots (no network), so a malformed update or an un-wired GUPPI/authorizer
never crashes the router and never silently mis-routes:

* a non-text / empty-text / message-less / chat-less update is a no-op drop;
* an open gateway (``authorizer=None``) treats every Bob-topic message as
  authorized (backward-compatible single-bot behaviour);
* a gateway built without GUPPI (or without an authorizer) falls back to a
  *silent* drop on both GUPPI hooks instead of raising;
* a text-less update reaching the General branch is dropped silently.
"""

from __future__ import annotations

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

    async def send_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        text: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not exercised by these drop-path tests
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover - not exercised here
        return _FakeMessage(message_id=0, text="")

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not exercised here
        return True


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


def _registry(bob: _FakeBot, guppi: _FakeBot | None) -> BotRegistry:
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob,
        scope=BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID),
    )
    if guppi is not None:
        registry.register(
            identity=BotIdentity.GUPPI,
            bot=guppi,
            scope=BotScope(chat_id=_CHAT_ID, topic_id=None),
        )
    return registry


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


def _bob_update(
    update_id: int,
    *,
    message: _FakeMessage | None,
    chat: _FakeChat | None = None,
    user_id: int = _OWNER_ID,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=message,
        effective_chat=chat if chat is not None else _FakeChat(id=_CHAT_ID),
        effective_user=_FakeUser(id=user_id),
    )


# --- Malformed updates are dropped (line: message/chat/text guard) ------------


@pytest.mark.parametrize(
    ("message", "chat"),
    [
        pytest.param(None, _FakeChat(id=_CHAT_ID), id="no_message"),
        pytest.param(_FakeMessage(message_id=1, text="hi"), None, id="no_chat"),
        pytest.param(
            _FakeMessage(message_id=1, text="", message_thread_id=_BOB_TOPIC_ID),
            _FakeChat(id=_CHAT_ID),
            id="empty_text",
        ),
        pytest.param(
            _FakeMessage(message_id=1, text=None, message_thread_id=_BOB_TOPIC_ID),
            _FakeChat(id=_CHAT_ID),
            id="none_text",
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_update_is_a_silent_noop(
    message: _FakeMessage | None,
    chat: _FakeChat | None,
) -> None:
    # Arrange
    bob, guppi = _FakeBot(), _FakeBot()
    bus = AsyncEventBus()
    gateway = MultiBotGateway(
        registry=_registry(bob, guppi),
        bus=bus,
        poll_timeout=10,
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    # Act
    published = await gateway.route(
        _bob_update(1, message=message, chat=chat), BotIdentity.BOB
    )

    # Assert: dropped, nothing published, neither bot spoke.
    assert published is False
    assert received == []
    assert bob.sends == []
    assert guppi.sends == []


# --- Open gateway: no authorizer => Bob-topic message is authorized -----------


@pytest.mark.asyncio
async def test_no_authorizer_treats_bob_topic_message_as_authorized() -> None:
    # Arrange: an "open" gateway (authorizer un-wired) keeps the pre-authz
    # single-bot behaviour — any Bob-topic message reaches his pipeline.
    bob, guppi = _FakeBot(), _FakeBot()
    bus = AsyncEventBus()
    gateway = MultiBotGateway(
        registry=_registry(bob, guppi), bus=bus, poll_timeout=10, authorizer=None
    )
    received = await _collect(bus)

    # Act
    published = await gateway.route(
        _bob_update(
            1,
            message=_FakeMessage(
                message_id=1, text="hi Bob", message_thread_id=_BOB_TOPIC_ID
            ),
            user_id=_STRANGER_ID,
        ),
        BotIdentity.BOB,
    )

    # Assert: published despite an unknown sender (no gate wired).
    assert published is True
    assert len(received) == 1


# --- GUPPI hooks fall back to silent drops when GUPPI is absent ---------------


@pytest.mark.asyncio
async def test_reject_hook_is_silent_when_guppi_not_registered() -> None:
    # Arrange: only Bob registered + a denying authorizer; the reject hook must
    # not raise even though there is no GUPPI to speak it.
    bob = _FakeBot()
    bus = AsyncEventBus()

    @dataclass
    class _Deny:
        def is_owner(self, user_id: int | None) -> bool:  # noqa: ARG002
            return False

        async def is_authorized(
            self, *, user_id: int | None, chat_id: int  # noqa: ARG002
        ) -> bool:
            return False

        async def authorize(self, user_id: int) -> None:  # pragma: no cover
            raise NotImplementedError

        async def deauthorize(self, user_id: int) -> None:  # pragma: no cover
            raise NotImplementedError

    gateway = MultiBotGateway(
        registry=_registry(bob, None), bus=bus, poll_timeout=10, authorizer=_Deny()
    )
    received = await _collect(bus)

    # Act: unauthorized in Bob's topic, but no GUPPI wired.
    published = await gateway.route(
        _bob_update(
            1,
            message=_FakeMessage(
                message_id=1, text="hi", message_thread_id=_BOB_TOPIC_ID
            ),
            user_id=_STRANGER_ID,
        ),
        BotIdentity.BOB,
    )

    # Assert: silent drop, Bob not invoked, no crash.
    assert published is False
    assert received == []
    assert bob.sends == []


@pytest.mark.asyncio
async def test_general_command_hook_is_silent_when_authorizer_unwired() -> None:
    # Arrange: GUPPI registered but no authorizer => _guppi is None, so a General
    # owner command is dropped silently rather than handled.
    bob, guppi = _FakeBot(), _FakeBot()
    bus = AsyncEventBus()
    gateway = MultiBotGateway(
        registry=_registry(bob, guppi), bus=bus, poll_timeout=10, authorizer=None
    )

    # Act: owner /authorize in General (no thread) with no authz wired.
    published = await gateway.route(
        _bob_update(
            1,
            message=_FakeMessage(
                message_id=1, text="/authorize 5", message_thread_id=None
            ),
            user_id=_OWNER_ID,
        ),
        BotIdentity.BOB,
    )

    # Assert: not Bob's pipeline, and GUPPI stays silent (no handler built).
    assert published is False
    assert guppi.sends == []
    assert bob.sends == []
