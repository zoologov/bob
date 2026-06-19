# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""GUPPI identity wired into the central router (BOB-003 BEAD-03).

These tests drive the two BEAD-02 drop-hooks now filled by GUPPI, end-to-end
through :class:`MultiBotGateway.route`/``poll_once`` with fake bots:

* **reject** — an unauthorized user in Bob's topic → GUPPI's bot sends the visible
  reject into the same chat + thread, and Bob's pipeline publishes nothing;
* **owner command** — owner ``/authorize <id>`` in General → GUPPI grants via the
  shared authorizer (persisted) and Bob never sees it;
* **non-owner command** — ignored (no grant, no send);
* **/status** — GUPPI answers;
* **stranger DM** — a foreign chat is silent (no reject, no send, no reveal).
"""

from __future__ import annotations

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
_FOREIGN_CHAT_ID = -100999


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
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
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

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str  # noqa: ARG002
    ) -> _FakeMessage:
        return _FakeMessage(message_id=message_id, text=text)

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool:  # noqa: ARG002
        return True

    async def send_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        text: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not used here
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover - not used here
        return _FakeMessage(message_id=0, text="")

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover - not used here
        return True


@dataclass
class _FakeAuthorizer:
    """Owner + allowlist stub recording grants; denies all is_authorized."""

    granted: list[int] = field(default_factory=list)
    revoked: list[int] = field(default_factory=list)
    allow_all: bool = False

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:
        return self.allow_all

    async def authorize(self, user_id: int) -> None:
        self.granted.append(user_id)

    async def deauthorize(self, user_id: int) -> None:
        self.revoked.append(user_id)


def _update(
    update_id: int,
    *,
    message_id: int = 1,
    text: str | None = "hi",
    chat_id: int = _CHAT_ID,
    thread_id: int | None = None,
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
    *, authorizer: _FakeAuthorizer
) -> tuple[MultiBotGateway, AsyncEventBus, _FakeBot, _FakeBot]:
    bus = AsyncEventBus()
    bob, guppi = _FakeBot(), _FakeBot()
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
    return gateway, bus, bob, guppi


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


# --- Reject -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_in_bob_topic_triggers_guppi_reject() -> None:
    authorizer = _FakeAuthorizer(allow_all=False)  # everyone denied
    gateway, bus, bob, guppi = _build(authorizer=authorizer)
    bob.updates_batches = [
        [_update(10, thread_id=_BOB_TOPIC_ID, user_id=_STRANGER_ID)]
    ]
    received = await _collect(bus)

    await gateway.poll_once()

    assert received == []  # Bob's pipeline NOT invoked
    assert len(guppi.sends) == 1  # GUPPI (not Bob) speaks
    assert guppi.sends[0].text == GUPPI_REJECT_TEXT
    assert guppi.sends[0].chat_id == _CHAT_ID
    assert guppi.sends[0].message_thread_id == _BOB_TOPIC_ID
    assert bob.sends == []


# --- Owner commands -----------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_authorize_in_general_grants_via_guppi() -> None:
    authorizer = _FakeAuthorizer(allow_all=True)
    gateway, bus, bob, guppi = _build(authorizer=authorizer)
    received = await _collect(bus)

    published = await gateway.route(
        _update(20, text="/authorize 12345", thread_id=None, user_id=_OWNER_ID),
        BotIdentity.GUPPI,
    )

    assert published is False  # not Bob's pipeline
    assert authorizer.granted == [12345]
    assert received == []
    assert bob.sends == []
    assert len(guppi.sends) == 1  # GUPPI confirms


@pytest.mark.asyncio
async def test_status_command_answered_by_guppi() -> None:
    authorizer = _FakeAuthorizer(allow_all=True)
    gateway, _, _, guppi = _build(authorizer=authorizer)

    published = await gateway.route(
        _update(21, text="/status", thread_id=None, user_id=_OWNER_ID),
        BotIdentity.GUPPI,
    )

    assert published is False
    assert len(guppi.sends) == 1
    assert "GUPPI" in guppi.sends[0].text


@pytest.mark.asyncio
async def test_non_owner_command_in_general_is_ignored() -> None:
    authorizer = _FakeAuthorizer(allow_all=True)
    gateway, _, bob, guppi = _build(authorizer=authorizer)

    published = await gateway.route(
        _update(22, text="/authorize 12345", thread_id=None, user_id=_STRANGER_ID),
        BotIdentity.GUPPI,
    )

    assert published is False
    assert authorizer.granted == []
    assert guppi.sends == []
    assert bob.sends == []


# --- Silence (stranger DM / disallowed chat) ----------------------------------


@pytest.mark.asyncio
async def test_stranger_dm_is_silent() -> None:
    authorizer = _FakeAuthorizer(allow_all=False)
    gateway, bus, bob, guppi = _build(authorizer=authorizer)
    received = await _collect(bus)

    published = await gateway.route(
        _update(
            23,
            text="hello?",
            chat_id=_FOREIGN_CHAT_ID,
            thread_id=None,
            user_id=_STRANGER_ID,
        ),
        BotIdentity.GUPPI,
    )

    assert published is False
    assert received == []
    assert guppi.sends == []  # no reject, no reveal
    assert bob.sends == []
