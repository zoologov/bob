# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Telegram gateway (transport-only: intake, dedup, streaming).

No real Telegram network: a hand-rolled fake bot records calls and can be told
to raise ``RetryAfter`` to drive the throttle/backoff path. A monotonic fake
clock + recording sleep make edit-batching deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from telegram.error import RetryAfter

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.domain import ports

# --- Test doubles -------------------------------------------------------------


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None


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
    chat_id: int = 100,
    text: str | None = "hello",
    message_id: int = 1,
    user: _FakeUser | None = None,
) -> _FakeUpdate:
    return _FakeUpdate(
        update_id=update_id,
        message=_FakeMessage(message_id=message_id, text=text),
        effective_chat=_FakeChat(id=chat_id),
        effective_user=user,
    )


@dataclass
class _SendCall:
    chat_id: int
    text: str


@dataclass
class _EditCall:
    chat_id: int
    message_id: int
    text: str


@dataclass
class _FakeBot:
    """Records send/edit calls; can be scripted to raise ``RetryAfter`` once."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    get_updates_calls: list[tuple[int, int]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    edits: list[_EditCall] = field(default_factory=list)
    next_message_id: int = 500
    edit_retry_after_on_call: int | None = None
    _edit_calls: int = 0

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        self.get_updates_calls.append((offset, timeout))
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(self, *, chat_id: int, text: str) -> _FakeMessage:
        self.sends.append(_SendCall(chat_id=chat_id, text=text))
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> None:
        self._edit_calls += 1
        if self.edit_retry_after_on_call == self._edit_calls:
            self.edit_retry_after_on_call = None
            raise RetryAfter(3)
        self.edits.append(_EditCall(chat_id=chat_id, message_id=message_id, text=text))


class _FakeClock:
    """Monotonic seconds source advanced explicitly or by the recording sleep."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _RecordingSleep:
    """Async sleep that records durations and advances the bound clock."""

    def __init__(self, clock: _FakeClock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        self.clock.value += seconds


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _make_gateway(bot: _FakeBot, **kwargs: Any) -> TelegramGateway:
    clock = kwargs.pop("clock", _FakeClock())
    sleep = kwargs.pop("sleep", _RecordingSleep(clock))
    bus = kwargs.pop("bus", AsyncEventBus())
    return TelegramGateway(
        bot=bot,
        bus=bus,
        poll_timeout=kwargs.pop("poll_timeout", 10),
        batch_tokens=kwargs.pop("batch_tokens", 3),
        throttle_interval=kwargs.pop("throttle_interval", 1.0),
        clock=clock,
        sleep=sleep,
    )


# --- Intake / dedup -----------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_publishes_message_received() -> None:
    bus = AsyncEventBus()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    published = await gateway.intake(
        _update(10, chat_id=42, text="hi bob", message_id=7)
    )

    assert published is True
    assert len(received) == 1
    assert received[0].chat_id == 42
    assert received[0].text == "hi bob"
    assert received[0].update_id == 10


@pytest.mark.asyncio
async def test_intake_deduplicates_by_update_id() -> None:
    bus = AsyncEventBus()
    count = 0

    async def handler(event: ports.DomainEvent) -> None:
        nonlocal count
        count += 1

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    first = await gateway.intake(_update(10))
    second = await gateway.intake(_update(10))

    assert first is True
    assert second is False
    assert count == 1


@pytest.mark.asyncio
async def test_intake_ignores_update_without_text() -> None:
    gateway = _make_gateway(_FakeBot())
    published = await gateway.intake(_update(10, text=None))
    assert published is False


@pytest.mark.asyncio
async def test_intake_carries_sender_metadata() -> None:
    bus = AsyncEventBus()
    received: list[MessageReceived] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        received.append(event)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(_FakeBot(), bus=bus)

    await gateway.intake(_update(10, user=_FakeUser(id=99, full_name="Alice")))

    assert received[0].sender_id == 99
    assert received[0].sender_name == "Alice"


@pytest.mark.asyncio
async def test_poll_once_consumes_batch_and_advances_offset() -> None:
    bot = _FakeBot(updates_batches=[[_update(10), _update(11)]])
    bus = AsyncEventBus()
    seen: list[int] = []

    async def handler(event: ports.DomainEvent) -> None:
        assert isinstance(event, MessageReceived)
        seen.append(event.update_id)

    bus.subscribe(MESSAGE_RECEIVED, handler)
    gateway = _make_gateway(bot, bus=bus)

    published = await gateway.poll_once()

    assert published == 2
    assert seen == [10, 11]
    # Next poll uses offset = last_update_id + 1; an empty batch is a no-op.
    assert await gateway.poll_once() == 0


@pytest.mark.asyncio
async def test_poll_once_dedup_persists_across_polls() -> None:
    bot = _FakeBot(updates_batches=[[_update(10)], [_update(10)]])
    gateway = _make_gateway(bot)

    first = await gateway.poll_once()
    second = await gateway.poll_once()

    assert first == 1
    assert second == 0


# --- Streaming reply: batching / throttle / backoff ---------------------------


@pytest.mark.asyncio
async def test_stream_reply_batches_edits_by_token_count() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    # batch_tokens=3, throttle disabled (interval 0) to isolate token batching.
    gateway = _make_gateway(
        bot, batch_tokens=3, throttle_interval=0.0, clock=clock, sleep=sleep
    )

    edits = await gateway.stream_reply(chat_id=42, tokens=_tokens("a", "b", "c", "d"))

    # One initial placeholder send.
    assert len(bot.sends) == 1
    assert bot.sends[0].chat_id == 42
    # Flush at 3 tokens ("abc") + final flush ("abcd"); both edits performed.
    assert edits == 2
    assert [e.text for e in bot.edits] == ["abc", "abcd"]
    assert all(e.message_id == 500 for e in bot.edits)


@pytest.mark.asyncio
async def test_stream_reply_throttles_edits_by_interval() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    # Flush every token by count, but throttle to one edit per 1.0s.
    gateway = _make_gateway(
        bot, batch_tokens=1, throttle_interval=1.0, clock=clock, sleep=sleep
    )

    await gateway.stream_reply(chat_id=7, tokens=_tokens("x", "y", "z"))

    # The gateway must have slept to honour the interval between edits.
    assert sleep.durations  # at least one throttle wait happened
    assert all(d <= 1.0 for d in sleep.durations)
    # Final text is the full accumulation.
    assert bot.edits[-1].text == "xyz"


@pytest.mark.asyncio
async def test_stream_reply_skips_redundant_final_edit() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    await gateway.stream_reply(chat_id=7, tokens=_tokens("only"))

    # "only" flushed once; no second identical edit.
    assert [e.text for e in bot.edits] == ["only"]


@pytest.mark.asyncio
async def test_stream_reply_backoff_on_rate_limit() -> None:
    bot = _FakeBot(edit_retry_after_on_call=1)
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    gateway = _make_gateway(
        bot, batch_tokens=1, throttle_interval=0.0, clock=clock, sleep=sleep
    )

    await gateway.stream_reply(chat_id=7, tokens=_tokens("a", "b"))

    # The first edit hit RetryAfter(3): we slept 3s then retried successfully.
    assert 3 in sleep.durations
    assert bot.edits[0].text == "a"


@pytest.mark.asyncio
async def test_stream_reply_empty_stream_sends_nothing_extra() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    edits = await gateway.stream_reply(chat_id=7, tokens=_tokens())

    # Placeholder was sent, but nothing to edit in.
    assert len(bot.sends) == 1
    assert edits == 0
    assert bot.edits == []
