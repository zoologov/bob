# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the gateway's single authorization gate (chat-scope + allowlist).

The gate is the one enforcement point: an unauthorized user OR a disallowed chat
is silently dropped (no ``MessageReceived`` published, no reply). The owner's
``/authorize <user_id>`` command adds a user to the persisted allowlist and is
itself never published as a message. A real :class:`Authorizer` over a fake
in-memory allowlist store drives these tests — no network, no SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.authz import Authorizer
from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.domain import ports

_OWNER = 1
_CHAT = 100


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _FakeUser:
    id: int
    full_name: str


@dataclass
class _FakeChat:
    id: int


@dataclass
class _FakeUpdate:
    update_id: int
    message: _FakeMessage | None = None
    effective_chat: _FakeChat | None = None
    effective_user: _FakeUser | None = None


def _update(
    update_id: int,
    *,
    chat_id: int = _CHAT,
    text: str | None = "hello",
    user_id: int | None = _OWNER,
) -> _FakeUpdate:
    user = _FakeUser(id=user_id, full_name="U") if user_id is not None else None
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(message_id=1, text=text),
        effective_chat=_FakeChat(id=chat_id),
        effective_user=user,
    )


@dataclass
class _SendCall:
    chat_id: int
    text: str


@dataclass
class _FakeBot:
    sends: list[_SendCall] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(_SendCall(chat_id=chat_id, text=text))
        return _FakeMessage(message_id=1, text=text)

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
    ) -> bool:
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        return _FakeMessage(message_id=1, text=rich_message.markdown)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True


class _FakeAllowlistStore:
    def __init__(self, initial: set[int] | None = None) -> None:
        self.users: set[int] = set(initial) if initial else set()

    async def load(self) -> set[int]:
        return set(self.users)

    async def add(self, user_id: int) -> None:
        self.users.add(user_id)

    async def remove(self, user_id: int) -> None:
        self.users.discard(user_id)


async def _monotonic() -> None:  # pragma: no cover - unused sleep seam
    return None


def _clock() -> float:
    return 0.0


def _gateway(
    *,
    bus: AsyncEventBus,
    bot: _FakeBot,
    store: _FakeAllowlistStore,
    allowed_chats: frozenset[int] = frozenset({_CHAT}),
) -> TelegramGateway:
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=allowed_chats, store=store
    )
    return TelegramGateway(
        bot=bot,
        bus=bus,
        poll_timeout=10,
        batch_tokens=3,
        throttle_interval=0.0,
        clock=_clock,
        sleep=lambda _seconds: _monotonic(),
        authorizer=authorizer,
    )


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


@pytest.mark.asyncio
async def test_owner_message_in_allowed_chat_is_published() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    gateway = _gateway(bus=bus, bot=_FakeBot(), store=_FakeAllowlistStore())

    published = await gateway.intake(_update(1, user_id=_OWNER))

    assert published is True
    assert len(received) == 1


@pytest.mark.asyncio
async def test_unauthorized_user_is_silently_dropped() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    bot = _FakeBot()
    gateway = _gateway(bus=bus, bot=bot, store=_FakeAllowlistStore())

    published = await gateway.intake(_update(1, user_id=555))

    assert published is False
    assert received == []
    assert bot.sends == []  # silent: no error reply


@pytest.mark.asyncio
async def test_disallowed_chat_is_silently_dropped_even_for_owner() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    bot = _FakeBot()
    gateway = _gateway(bus=bus, bot=bot, store=_FakeAllowlistStore())

    published = await gateway.intake(_update(1, chat_id=999, user_id=_OWNER))

    assert published is False
    assert received == []
    assert bot.sends == []


@pytest.mark.asyncio
async def test_allowlisted_user_in_allowed_chat_is_published() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    store = _FakeAllowlistStore(initial={555})
    gateway = _gateway(bus=bus, bot=_FakeBot(), store=store)

    published = await gateway.intake(_update(1, user_id=555))

    assert published is True
    assert len(received) == 1


@pytest.mark.asyncio
async def test_owner_authorize_command_adds_user_and_is_not_published() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    store = _FakeAllowlistStore()
    bot = _FakeBot()
    gateway = _gateway(bus=bus, bot=bot, store=store)

    published = await gateway.intake(
        _update(1, text="/authorize 555", user_id=_OWNER)
    )

    assert published is False  # the command itself is not a chat message
    assert received == []
    assert store.users == {555}
    assert len(bot.sends) == 1  # owner gets a confirmation


@pytest.mark.asyncio
async def test_then_authorized_user_can_talk() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    store = _FakeAllowlistStore()
    gateway = _gateway(bus=bus, bot=_FakeBot(), store=store)

    await gateway.intake(_update(1, text="/authorize 555", user_id=_OWNER))
    published = await gateway.intake(_update(2, user_id=555))

    assert published is True
    assert len(received) == 1


@pytest.mark.asyncio
async def test_non_owner_authorize_command_is_ignored() -> None:
    bus = AsyncEventBus()
    received = await _collect(bus)
    store = _FakeAllowlistStore(initial={555})
    bot = _FakeBot()
    gateway = _gateway(bus=bus, bot=bot, store=store)

    # 555 is allowlisted (so the gate lets them in) but is NOT the owner: the
    # privileged command must not grant anyone. The text falls through as an
    # ordinary message, but no authorization grant occurs.
    published = await gateway.intake(
        _update(1, text="/authorize 777", user_id=555)
    )

    assert 777 not in store.users
    assert published is True
    assert len(received) == 1


@pytest.mark.asyncio
async def test_owner_deauthorize_command_revokes_access() -> None:
    bus = AsyncEventBus()
    await _collect(bus)
    store = _FakeAllowlistStore(initial={555})
    gateway = _gateway(bus=bus, bot=_FakeBot(), store=store)

    await gateway.intake(_update(1, text="/deauthorize 555", user_id=_OWNER))

    assert 555 not in store.users


@pytest.mark.asyncio
async def test_no_authorizer_means_no_gate() -> None:
    # Backward-compatible: a gateway built without an authorizer publishes all
    # text updates (the gate is opt-in via wiring).
    bus = AsyncEventBus()
    received = await _collect(bus)
    gateway = TelegramGateway(
        bot=_FakeBot(),
        bus=bus,
        poll_timeout=10,
        batch_tokens=3,
        throttle_interval=0.0,
        clock=_clock,
        sleep=lambda _s: _monotonic(),
    )

    published = await gateway.intake(_update(1, chat_id=999, user_id=555))

    assert published is True
    assert len(received) == 1
