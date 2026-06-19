# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening for the Telegram gateway — construction guards, gate edges, rich draft.

Complements ``test_gateway.py`` (streaming/rich happy paths) and
``test_gateway_authz.py`` (the gate's authorize/deny matrix) by pinning the
remaining behavioural edges:

* construction rejects nonsensical batching/throttle config (US-1 robustness);
* the gate drops an update with no chat even when an authorizer is wired (US-2);
* the owner ``/authorize`` command with a missing/invalid argument is answered
  with a usage hint, granting nobody (US-2 — no silent bad grant);
* a rich **draft** that hits a Telegram rate-limit backs off and retries, and a
  rich draft that errors is skipped without killing the stream (US-1 streaming
  resilience), while the committed reply still lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage, SendRichMessageDraft

from bob.application.authz import Authorizer
from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

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


@dataclass
class _SendCall:
    chat_id: int
    text: str


@dataclass
class _RichDraftCall:
    chat_id: int
    markdown: str | None


@dataclass
class _FakeBot:
    """Records sends + rich drafts; can be scripted to raise on a given draft."""

    sends: list[_SendCall] = field(default_factory=list)
    rich_sends: list[tuple[int, str | None]] = field(default_factory=list)
    rich_drafts: list[_RichDraftCall] = field(default_factory=list)
    rich_draft_retry_after_on_call: int | None = None
    rich_draft_bad_request_on_call: int | None = None
    _rich_draft_calls: int = 0

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[_FakeUpdate]:
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
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
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.rich_sends.append((chat_id, rich_message.markdown))
        return _FakeMessage(message_id=1, text=rich_message.markdown)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        self._rich_draft_calls += 1
        if self.rich_draft_retry_after_on_call == self._rich_draft_calls:
            self.rich_draft_retry_after_on_call = None
            raise TelegramRetryAfter(
                method=SendRichMessageDraft(
                    chat_id=chat_id, draft_id=draft_id, rich_message=rich_message
                ),
                message="flood",
                retry_after=2,
            )
        if self.rich_draft_bad_request_on_call == self._rich_draft_calls:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich draft rejected",
            )
        self.rich_drafts.append(
            _RichDraftCall(chat_id=chat_id, markdown=rich_message.markdown)
        )
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


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _RecordingSleep:
    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self.clock.value += seconds


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _gateway(
    bot: _FakeBot,
    *,
    bus: AsyncEventBus | None = None,
    with_authz: bool = False,
    clock: _FakeClock | None = None,
    sleep: _RecordingSleep | None = None,
    batch_tokens: int = 1,
    throttle_interval: float = 0.0,
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
        batch_tokens=batch_tokens,
        throttle_interval=throttle_interval,
        clock=clk,
        sleep=slp,
        authorizer=authorizer,
    )


# --- Construction guards (US-1 robustness) ------------------------------------


def test_construction_rejects_non_positive_batch_tokens() -> None:
    with pytest.raises(ValueError, match="batch_tokens"):
        _gateway(_FakeBot(), batch_tokens=0)


def test_construction_rejects_negative_throttle_interval() -> None:
    with pytest.raises(ValueError, match="throttle_interval"):
        _gateway(_FakeBot(), throttle_interval=-1.0)


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
        batch_tokens=1,
        throttle_interval=0.0,
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
        batch_tokens=1,
        throttle_interval=0.0,
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
        batch_tokens=1,
        throttle_interval=0.0,
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


# --- Rich draft resilience (US-1 streaming) -----------------------------------


@pytest.mark.asyncio
async def test_rich_draft_backs_off_and_retries_on_rate_limit() -> None:
    # The first rich draft hits RetryAfter(2): the gateway sleeps then retries, so
    # the partial still streams and the reply commits.
    bot = _FakeBot(rich_draft_retry_after_on_call=1)
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    gateway = _gateway(
        bot, clock=clock, sleep=sleep, batch_tokens=1, throttle_interval=0.0
    )

    await gateway.stream_reply_rich(chat_id=_CHAT, tokens=_tokens("a", "b"))

    assert 2 in sleep.durations  # backed off the advertised retry_after
    assert bot.rich_drafts  # retry succeeded, a draft landed
    assert bot.rich_sends  # the finished reply still committed


@pytest.mark.asyncio
async def test_rich_draft_error_is_skipped_without_killing_the_stream() -> None:
    # A non-rate-limit rich-draft error must be swallowed without killing the stream
    # (US-1 streaming resilience). Drafting is best-effort: once a chat rejects a
    # draft the gateway STOPS attempting drafts for the rest of the turn (BOB-004), so
    # only the first partial is attempted — but the finished reply still commits via
    # the rich channel, so the user always receives the answer.
    bot = _FakeBot(rich_draft_bad_request_on_call=1)
    gateway = _gateway(bot, batch_tokens=1, throttle_interval=0.0)

    drafts = await gateway.stream_reply_rich(chat_id=_CHAT, tokens=_tokens("a", "b"))

    # The first partial was attempted and rejected; the second skipped the draft
    # channel entirely. The reply still committed via the rich channel.
    assert drafts == 1
    assert bot.rich_sends
    assert bot.rich_sends[-1][1] == "ab"


async def _noop() -> None:
    return None
