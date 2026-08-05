# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening for the Telegram gateway — construction guards, gate edges, resilience.

Complements ``test_gateway.py`` (typing/rich happy paths) and
``test_gateway_authz.py`` (the gate's authorize/deny matrix) by pinning the
remaining behavioural edges (BOB-008, Variant A):

* construction rejects a non-positive ``typing_interval`` (US-1 robustness);
* the gate drops an update with no chat even when an authorizer is wired (US-2);
* the owner ``/authorize`` command with a missing/invalid argument is answered
  with a usage hint, granting nobody (US-2 — no silent bad grant);
* a failing ``sendChatAction`` is swallowed (best-effort typing), and the finished
  reply still commits via the rich channel — the answer is never lost.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import TelegramGateway
from bob.social.usecases import Authorizer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.kernel import ports

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
    text: str


@dataclass
class _FakeBot:
    """Records sends + rich finals; can be scripted to fail the typing action."""

    sends: list[_SendCall] = field(default_factory=list)
    rich_sends: list[tuple[int, str | None]] = field(default_factory=list)
    typings: int = 0
    typing_raises: bool = False

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(_SendCall(chat_id=chat_id, text=text))
        return _FakeMessage(message_id=1, text=text)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        if self.typing_raises:
            raise ValueError("typing boom")
        self.typings += 1
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,# noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.rich_sends.append((chat_id, rich_message.markdown))
        return _FakeMessage(message_id=1, text=rich_message.markdown)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

class _FakeAllowlistStore:
    def __init__(self, initial: set[int] | None = None) -> None:
        self.users: set[int] = set(initial) if initial else set()

    async def load(self) -> set[int]:
        return set(self.users)

    async def add(self, user_id: int) -> None:
        self.users.add(user_id)

    async def remove(self, user_id: int) -> None:
        self.users.discard(user_id)


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _RecordingSleep:
    """Async sleep that records durations, advances the bound clock, and yields.

    The ``await asyncio.sleep(0)`` is essential: the typing keepalive runs a
    ``while True`` loop driven by this injected sleep, so the fake MUST hand
    control back to the event loop on every tick. A no-op (``async def f(): pass``)
    would starve the loop — the keepalive would spin at 100% CPU and the
    surrounding context body / ``task.cancel()`` would never get scheduled.
    """

    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self.clock.value += seconds
        await asyncio.sleep(0)


def _gateway(
    bot: _FakeBot,
    *,
    bus: AsyncEventBus | None = None,
    with_authz: bool = False,
    clock: _FakeClock | None = None,
    sleep: _RecordingSleep | None = None,
    typing_interval: float = 4.0,
) -> TelegramGateway:
    clk = clock or _FakeClock()
    slp = sleep or _RecordingSleep(clk)
    authorizer = (
        Authorizer(
            owner_id=_OWNER,
            allowed_chat_ids=frozenset({_CHAT}),
            store=_FakeAllowlistStore(),
        )
        if with_authz
        else None
    )
    return TelegramGateway(
        bot=bot,
        bus=bus or AsyncEventBus(),
        poll_timeout=10,
        typing_interval=typing_interval,
        clock=clk,
        sleep=slp,
        authorizer=authorizer,
    )


# --- Construction guards (US-1 robustness) ------------------------------------


def test_construction_rejects_non_positive_typing_interval() -> None:
    with pytest.raises(ValueError, match="typing_interval"):
        _gateway(_FakeBot(), typing_interval=0.0)


# --- Gate edges (US-2) --------------------------------------------------------


@pytest.mark.asyncio
async def test_update_without_chat_is_dropped_when_gated() -> None:
    # An update carrying no effective_chat cannot be scoped, so the gate drops it
    # even with an authorizer wired — no MessageReceived, no reply.
    bus = AsyncEventBus()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _gateway(_FakeBot(), bus=bus, with_authz=True)

    published = await gateway.intake(
        _FakeUpdate(
            update_id=1,
            message=_FakeMessage(message_id=1, text="hi"),
            effective_chat=None,
            effective_user=_FakeUser(id=_OWNER, full_name="Owner"),
        )
    )

    assert published is False
    assert received == []


@pytest.mark.asyncio
async def test_owner_authorize_with_missing_argument_answers_usage_and_grants_nobody() -> None:
    bot = _FakeBot()
    store = _FakeAllowlistStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=frozenset({_CHAT}), store=store
    )
    bus = AsyncEventBus()
    gateway = TelegramGateway(
        bot=bot,
        bus=bus,
        poll_timeout=10,
        typing_interval=4.0,
        clock=_FakeClock(),
        sleep=lambda _s: _noop(),
        authorizer=authorizer,
    )

    published = await gateway.intake(
        _FakeUpdate(
            update_id=1,
            message=_FakeMessage(message_id=1, text="/authorize"),
            effective_chat=_FakeChat(id=_CHAT),
            effective_user=_FakeUser(id=_OWNER, full_name="Owner"),
        )
    )

    # The command was consumed (not published); a usage hint went back; no grant.
    assert published is False
    assert store.users == set()
    assert len(bot.sends) == 1
    assert "Usage:" in bot.sends[0].text


@pytest.mark.asyncio
async def test_owner_authorize_with_non_numeric_argument_answers_usage() -> None:
    bot = _FakeBot()
    store = _FakeAllowlistStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=frozenset({_CHAT}), store=store
    )
    gateway = TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        typing_interval=4.0,
        clock=_FakeClock(),
        sleep=lambda _s: _noop(),
        authorizer=authorizer,
    )

    await gateway.intake(
        _FakeUpdate(
            update_id=1,
            message=_FakeMessage(message_id=1, text="/authorize not-a-number"),
            effective_chat=_FakeChat(id=_CHAT),
            effective_user=_FakeUser(id=_OWNER, full_name="Owner"),
        )
    )

    assert store.users == set()
    assert "Usage:" in bot.sends[0].text


@pytest.mark.asyncio
async def test_owner_authorize_accepts_negative_user_id() -> None:
    # Telegram chat/user ids can be negative; the parser must accept a leading '-'.
    bot = _FakeBot()
    store = _FakeAllowlistStore()
    authorizer = Authorizer(
        owner_id=_OWNER, allowed_chat_ids=frozenset({_CHAT}), store=store
    )
    gateway = TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        typing_interval=4.0,
        clock=_FakeClock(),
        sleep=lambda _s: _noop(),
        authorizer=authorizer,
    )

    await gateway.intake(
        _FakeUpdate(
            update_id=1,
            message=_FakeMessage(message_id=1, text="/authorize -42"),
            effective_chat=_FakeChat(id=_CHAT),
            effective_user=_FakeUser(id=_OWNER, full_name="Owner"),
        )
    )

    assert store.users == {-42}


# --- Typing resilience (US-1) -------------------------------------------------


class _GatedSleep:
    """Async sleep that parks on an event until the test releases one tick.

    Models one ``typing_interval`` of generation per :meth:`tick`, with no
    wall-clock wait and no busy-spin: the keepalive blocks on the gate between
    ticks instead of looping freely.
    """

    def __init__(self) -> None:
        self.durations: list[float] = []
        self._gate = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self._gate.clear()
        await self._gate.wait()

    def tick(self) -> None:
        self._gate.set()


@pytest.mark.asyncio
async def test_typing_action_failure_is_swallowed_and_reply_still_lands() -> None:
    # A failing sendChatAction must not break the turn: typing is best-effort, so the
    # typing_indicator context still enters/exits cleanly and the finished reply
    # commits via the rich channel. The gated sleep parks the keepalive (no spin).
    bot = _FakeBot(typing_raises=True)
    gateway = TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        typing_interval=4.0,
        clock=_FakeClock(),
        sleep=_GatedSleep(),
    )

    async with gateway.typing_indicator(chat_id=_CHAT):
        await asyncio.sleep(0)
    await gateway.reply(chat_id=_CHAT, markdown="ab")

    assert bot.typings == 0  # no typing landed, but it did not crash
    assert bot.rich_sends  # the reply still committed
    assert bot.rich_sends[-1][1] == "ab"


async def _noop() -> None:
    return None
