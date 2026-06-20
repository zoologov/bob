# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Telegram gateway (transport-only: intake, dedup, typing+rich reply).

No real Telegram network: a hand-rolled fake aiogram-style bot records calls. A
monotonic fake clock makes the "Bob is typing…" cadence deterministic.

BOB-008 (Variant A): native streaming is gone — Bob is reached only through a group
topic, where drafts are DM-only and edits are slow + flood-prone. The reply path now
shows ``sendChatAction("typing")`` while it assembles the reply, then commits a single
rich ``send_rich_message`` (degrading to a plain ``send_message`` on a rich error).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.events import MESSAGE_RECEIVED, MessageReceived
from bob.infrastructure.telegram.gateway import PLAIN_TEXT_LIMIT, TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

    from bob.domain import ports

# --- Test doubles -------------------------------------------------------------


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
    message_thread_id: int | None


@dataclass
class _TypingCall:
    chat_id: int
    action: str
    message_thread_id: int | None


@dataclass
class _RichCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Records send/typing/rich calls; can be scripted to fail the rich final."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    get_updates_calls: list[tuple[int, int]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    typings: list[_TypingCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    next_message_id: int = 500
    rich_send_raises: bool = False

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        self.get_updates_calls.append((offset, timeout))
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
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:
        self.typings.append(
            _TypingCall(
                chat_id=chat_id, action=action, message_thread_id=message_thread_id
            )
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.rich_send_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich rejected",
            )
        self.rich_sends.append(
            _RichCall(
                chat_id=chat_id,
                markdown=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=rich_message.markdown)
        self.next_message_id += 1
        return msg


class _FakeClock:
    """Monotonic seconds source advanced explicitly (drives the typing cadence)."""

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
        typing_interval=kwargs.pop("typing_interval", 4.0),
        clock=clock,
        sleep=sleep,
        reply_thread_id=kwargs.pop("reply_thread_id", None),
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


# --- Reply: typing indicator + single rich final (Variant A) ------------------


@pytest.mark.asyncio
async def test_stream_reply_shows_typing_then_one_rich_final() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, reply_thread_id=37)

    await gateway.stream_reply(chat_id=42, tokens=_tokens("Hel", "lo ", "world"))

    # "Bob is typing…" fired at least once, pinned to Bob's thread.
    assert bot.typings, "no typing indicator was sent during generation"
    assert all(t.action == "typing" for t in bot.typings)
    assert all(t.message_thread_id == 37 for t in bot.typings)
    # Exactly ONE rich final into the thread; no plain send.
    assert len(bot.rich_sends) == 1
    assert bot.rich_sends[0].markdown == "Hello world"
    assert bot.rich_sends[0].message_thread_id == 37
    assert bot.sends == []


@pytest.mark.asyncio
async def test_stream_reply_repeats_typing_on_interval_for_long_generation() -> None:
    # A long generation keeps re-sending "typing…": the injected clock advances past
    # the typing_interval between tokens, so the indicator is re-sent each interval.
    bot = _FakeBot()
    clock = _FakeClock()

    async def slow_tokens() -> AsyncIterator[str]:
        for token in ("a", "b", "c"):
            clock.value += 5.0  # > typing_interval=4.0, so each token re-types
            yield token

    gateway = _make_gateway(
        bot, clock=clock, sleep=_RecordingSleep(clock), typing_interval=4.0
    )

    await gateway.stream_reply(chat_id=7, tokens=slow_tokens())

    # One up-front action + one per elapsed interval (3 tokens) = 4 typing actions.
    assert len(bot.typings) >= 2, "typing was not repeated for a long generation"
    assert len(bot.rich_sends) == 1


@pytest.mark.asyncio
async def test_stream_reply_renders_thinking_block() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.stream_reply(
        chat_id=7, tokens=_tokens("answer"), thinking="my private reasoning"
    )

    assert len(bot.rich_sends) == 1
    markdown = bot.rich_sends[0].markdown or ""
    assert "my private reasoning" in markdown
    assert markdown.strip().endswith("answer")


@pytest.mark.asyncio
async def test_stream_reply_rich_failure_falls_back_to_plain() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot, reply_thread_id=37)

    await gateway.stream_reply(chat_id=7, tokens=_tokens("hel", "lo"))

    # Rich failed → the reply is NOT lost: it lands via a plain send into the thread.
    assert bot.rich_sends == []
    assert len(bot.sends) == 1
    assert bot.sends[0].text == "hello"
    assert bot.sends[0].message_thread_id == 37


@pytest.mark.asyncio
async def test_stream_reply_no_edit_or_draft_calls() -> None:
    # The fake bot has no edit/draft methods at all; this just pins that the gateway
    # only ever uses typing + rich/plain — a regression guard against streaming.
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.stream_reply(chat_id=7, tokens=_tokens("x", "y", "z"))

    assert not hasattr(bot, "edits")
    assert not hasattr(bot, "drafts")
    assert len(bot.rich_sends) == 1


@pytest.mark.asyncio
async def test_stream_reply_empty_stream_sends_nothing_but_may_type() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    actions = await gateway.stream_reply(chat_id=7, tokens=_tokens())

    # Nothing to commit; the up-front typing action may still have fired.
    assert actions >= 0
    assert bot.rich_sends == []
    assert bot.sends == []


# --- Rich reply: send_rich_message + thinking + plain fallback ----------------


@pytest.mark.asyncio
async def test_reply_rich_sends_rich_message() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="a **bold** word")

    assert len(bot.rich_sends) == 1
    assert bot.rich_sends[0].chat_id == 7
    assert bot.rich_sends[0].markdown == "a **bold** word"
    assert bot.sends == []


@pytest.mark.asyncio
async def test_reply_rich_renders_thinking_block() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="the answer", thinking="be brief")

    assert len(bot.rich_sends) == 1
    sent = bot.rich_sends[0].markdown
    assert sent is not None
    assert "be brief" in sent
    assert sent.strip().endswith("the answer")


@pytest.mark.asyncio
async def test_reply_falls_back_to_plain_on_rich_error() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="hello **world**")

    assert bot.rich_sends == []
    assert len(bot.sends) == 1
    assert bot.sends[0].chat_id == 7
    assert bot.sends[0].text == "hello **world**"


@pytest.mark.asyncio
async def test_reply_plain_fallback_splits_on_length_limit() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot)
    long_text = "x" * (PLAIN_TEXT_LIMIT + 50)

    await gateway.reply(chat_id=7, markdown=long_text)

    assert len(bot.sends) == 2
    assert all(len(s.text) <= PLAIN_TEXT_LIMIT for s in bot.sends)
    assert "".join(s.text for s in bot.sends) == long_text


@pytest.mark.asyncio
async def test_reply_empty_markdown_without_thinking_sends_nothing() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot)

    await gateway.reply(chat_id=7, markdown="   ")

    assert bot.rich_sends == []
    assert bot.sends == []
