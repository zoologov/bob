# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the multi-bot gateway (BOB-003 BEAD-02).

One central router polls BOTH admin bots (Bob + GUPPI) with fake aiogram bots
(no network). The tests cover the four things this bead owns:

* **cross-bot dedup** — a group message both admin bots see (delivered twice)
  is processed exactly once, keyed on ``(chat_id, message_id)`` — independent of
  which bot delivered it;
* **identity-routing** — the router receives ``(update, bot_identity)`` and an
  authorized message in Bob's topic publishes one :class:`MessageReceived`;
* **Bob topic-filter** — only ``chat_id == bob.chat_id`` AND
  ``message_thread_id == bob.topic_id`` reaches Bob's pipeline; General (no
  thread) and other topics are dropped (no crash);
* **thread-reply** — Bob's reply streamer sets ``message_thread_id`` so replies
  land in his thread;
* **two-bot isolation** — one bot raising on poll does not stop the other.

The unauthorized branch and the GUPPI/owner-command branch are BEAD-03; here they
are just drop-hooks, so this bead's router never crashes on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram import multibot
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

    from bob.domain import ports

# Target ids from the epic (CONTEXT.md): the group, Bob's topic, the owner.
_CHAT_ID = -1004372947307
_BOB_TOPIC_ID = 32
_OWNER_ID = 27468732


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
class _TypingCall:
    chat_id: int
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records sends/typing; serves scripted update batches; can fail one poll."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    typings: list[_TypingCall] = field(default_factory=list)
    next_message_id: int = 900
    raise_on_poll: bool = False

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        if self.raise_on_poll:
            raise RuntimeError("boom")
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
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        self.typings.append(
            _TypingCall(chat_id=chat_id, message_thread_id=message_thread_id)
        )
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


class _AllowAuthorizer:
    """Authorizer stub: authorizes everyone (Bob path under test)."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:
        return True

    async def authorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover - unused here

    async def deauthorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover - unused here


class _DenyAuthorizer:
    """Authorizer stub: denies everyone (unauthorized drop-hook under test)."""

    def is_owner(self, user_id: int | None) -> bool:  # noqa: ARG002
        return False

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int  # noqa: ARG002
    ) -> bool:
        return False

    async def authorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover - unused here

    async def deauthorize(self, user_id: int) -> None:
        raise NotImplementedError  # pragma: no cover - unused here


def _bob_topic_update(
    update_id: int,
    *,
    message_id: int = 1,
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
    bots: dict[BotIdentity, _FakeBot],
    *,
    authorizer: _AllowAuthorizer | _DenyAuthorizer | None = None,
    bus: AsyncEventBus | None = None,
) -> tuple[MultiBotGateway, AsyncEventBus]:
    bus = bus if bus is not None else AsyncEventBus()
    registry = BotRegistry()
    bob_scope = BotScope(chat_id=_CHAT_ID, topic_id=_BOB_TOPIC_ID)
    registry.register(
        identity=BotIdentity.BOB, bot=bots[BotIdentity.BOB], scope=bob_scope
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
        authorizer=authorizer,
        # Deterministic reply timing: a fixed clock + no-op sleep so the typing
        # cadence never actually waits in tests.
        reply_typing_interval=4.0,
        reply_clock=lambda: 0.0,
        reply_sleep=_noop_sleep,
    )
    return gateway, bus


async def _noop_sleep(_seconds: float) -> None:
    return None


async def _collect(bus: AsyncEventBus) -> list[MessageReceived]:
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    return received


# --- Identity-routing + topic filter ------------------------------------------


@pytest.mark.asyncio
async def test_authorized_bob_topic_message_publishes_once() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_bob_topic_update(10)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert len(received) == 1
    assert received[0].chat_id == _CHAT_ID
    assert received[0].text == "hi Bob"


@pytest.mark.asyncio
async def test_router_receives_bot_identity_and_publishes_bob_path() -> None:
    """The central router takes (update, identity); a Bob-topic update publishes."""
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    # The (update, identity) seam: GUPPI may deliver a Bob-topic group message.
    published = await gateway.route(_bob_topic_update(1), BotIdentity.GUPPI)

    assert published is True
    assert len(received) == 1


@pytest.mark.asyncio
async def test_general_message_is_dropped() -> None:
    """A message in General (no thread) never reaches Bob's pipeline."""
    bob, guppi = _FakeBot(), _FakeBot()
    guppi.updates_batches = [[_bob_topic_update(20, thread_id=None)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert received == []


@pytest.mark.asyncio
async def test_other_topic_message_is_dropped() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_bob_topic_update(21, thread_id=999)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert received == []


@pytest.mark.asyncio
async def test_unauthorized_bob_topic_message_is_dropped() -> None:
    """Unauthorized branch is a drop-hook in this bead (GUPPI reject is BEAD-03)."""
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_bob_topic_update(22)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_DenyAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert received == []


# --- Cross-bot dedup ----------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_bot_dedup_processes_once() -> None:
    """The same (chat_id, message_id) seen by both bots is processed once."""
    bob, guppi = _FakeBot(), _FakeBot()
    # Same chat+message, distinct update_ids (each bot has its own update stream).
    bob.updates_batches = [[_bob_topic_update(100, message_id=7)]]
    guppi.updates_batches = [[_bob_topic_update(200, message_id=7)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert len(received) == 1


@pytest.mark.asyncio
async def test_distinct_messages_both_processed() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    bob.updates_batches = [[_bob_topic_update(100, message_id=7)]]
    guppi.updates_batches = [[_bob_topic_update(200, message_id=8)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    await gateway.poll_once()

    assert len(received) == 2


# --- Two-bot isolation --------------------------------------------------------


@pytest.mark.asyncio
async def test_one_bot_poll_failure_does_not_kill_the_other() -> None:
    bob, guppi = _FakeBot(), _FakeBot()
    guppi.raise_on_poll = True  # GUPPI's poll explodes
    bob.updates_batches = [[_bob_topic_update(30)]]
    gateway, bus = _build(
        {BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi},
        authorizer=_AllowAuthorizer(),
    )
    received = await _collect(bus)

    # Must not raise; Bob's update still gets through.
    await gateway.poll_once()

    assert len(received) == 1


# --- Thread-reply -------------------------------------------------------------


@pytest.mark.asyncio
async def test_bob_reply_streamer_sets_thread_id() -> None:
    """Bob's reply streamer pins message_thread_id to his topic.

    BOB-008 (Variant A): Bob's topic shows a "typing…" indicator while generating,
    then commits one rich final — both the typing action and the rich final are
    pinned to Bob's thread; no streaming.
    """
    bob, guppi = _FakeBot(), _FakeBot()
    gateway, _ = _build({BotIdentity.BOB: bob, BotIdentity.GUPPI: guppi})
    streamer = gateway.reply_streamer(BotIdentity.BOB)

    async def _tokens() -> AsyncIterator[str]:
        for tok in ("hel", "lo"):
            yield tok

    await streamer.stream_reply(chat_id=_CHAT_ID, tokens=_tokens())

    assert bob.sends, "Bob's bot should have received the committed reply"
    assert all(call.message_thread_id == _BOB_TOPIC_ID for call in bob.sends)
    assert bob.typings, "the topic should have shown a typing indicator"
    assert all(call.message_thread_id == _BOB_TOPIC_ID for call in bob.typings)
    assert guppi.sends == []  # GUPPI never sends Bob's reply


def test_live_inner_gateways_use_real_clock_and_sleep() -> None:
    """The live wiring must drive the typing cadence with a real clock + sleep.

    BOB-008: the typing indicator is re-sent every ``_DEFAULT_TYPING_INTERVAL``
    seconds of generation, driven by a real monotonic clock + real sleep — not the
    deterministic test stubs.
    """
    assert multibot._DEFAULT_TYPING_INTERVAL > 0
    assert multibot._LIVE_CLOCK is not multibot._zero_clock
    assert multibot._LIVE_SLEEP is not multibot._noop_sleep
