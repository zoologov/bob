# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Telegram gateway (transport-only: intake, dedup, streaming).

No real Telegram network: a hand-rolled fake aiogram-style bot records calls and
can be told to raise ``TelegramRetryAfter`` to drive the throttle/backoff path. A
monotonic fake clock + recording sleep make draft batching deterministic.

Streaming uses aiogram's native ``send_message_draft`` (progressive draft) rather
than the old ``editMessageText`` loop: drafts stream the partial text, and a final
``send_message`` commits the completed reply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage, SendMessageDraft

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


@dataclass
class _DraftCall:
    chat_id: int
    draft_id: int
    text: str


@dataclass
class _RichCall:
    chat_id: int
    markdown: str | None


@dataclass
class _RichDraftCall:
    chat_id: int
    draft_id: int
    markdown: str | None


@dataclass
class _FakeBot:
    """Records send/draft calls; can be scripted to raise Telegram errors."""

    updates_batches: list[list[_FakeUpdate]] = field(default_factory=list)
    get_updates_calls: list[tuple[int, int]] = field(default_factory=list)
    sends: list[_SendCall] = field(default_factory=list)
    drafts: list[_DraftCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    rich_drafts: list[_RichDraftCall] = field(default_factory=list)
    next_message_id: int = 500
    draft_retry_after_on_call: int | None = None
    rich_send_raises: bool = False
    rich_draft_raises: bool = False
    _draft_calls: int = 0

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[_FakeUpdate]:
        self.get_updates_calls.append((offset, timeout))
        if not self.updates_batches:
            return []
        return self.updates_batches.pop(0)

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(_SendCall(chat_id=chat_id, text=text))
        msg = _FakeMessage(message_id=self.next_message_id, text=text)
        self.next_message_id += 1
        return msg

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        self._draft_calls += 1
        if self.draft_retry_after_on_call == self._draft_calls:
            self.draft_retry_after_on_call = None
            raise TelegramRetryAfter(
                method=SendMessageDraft(chat_id=chat_id, draft_id=draft_id, text=text),
                message="flood",
                retry_after=3,
            )
        self.drafts.append(
            _DraftCall(chat_id=chat_id, draft_id=draft_id, text=text)
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        if self.rich_send_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich rejected",
            )
        self.rich_sends.append(
            _RichCall(chat_id=chat_id, markdown=rich_message.markdown)
        )
        msg = _FakeMessage(message_id=self.next_message_id, text=rich_message.markdown)
        self.next_message_id += 1
        return msg

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        if self.rich_draft_raises:
            raise TelegramBadRequest(
                method=SendMessage(chat_id=chat_id, text=""),
                message="rich draft rejected",
            )
        self.rich_drafts.append(
            _RichDraftCall(
                chat_id=chat_id, draft_id=draft_id, markdown=rich_message.markdown
            )
        )
        return True


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


# --- Streaming reply: draft batching / throttle / backoff / commit ------------


@pytest.mark.asyncio
async def test_stream_reply_batches_drafts_by_token_count() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    # batch_tokens=3, throttle disabled (interval 0) to isolate token batching.
    gateway = _make_gateway(
        bot, batch_tokens=3, throttle_interval=0.0, clock=clock, sleep=sleep
    )

    drafts = await gateway.stream_reply(chat_id=42, tokens=_tokens("a", "b", "c", "d"))

    # A draft is streamed once 3 tokens accumulate ("abc"); the final remainder
    # ("abcd") is committed as a real message, not a draft.
    assert drafts == 1
    assert [d.text for d in bot.drafts] == ["abc"]
    assert all(d.chat_id == 42 for d in bot.drafts)
    # The completed reply is committed via send_message.
    assert len(bot.sends) == 1
    assert bot.sends[0].chat_id == 42
    assert bot.sends[0].text == "abcd"


@pytest.mark.asyncio
async def test_stream_reply_uses_a_single_draft_id() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    await gateway.stream_reply(chat_id=7, tokens=_tokens("a", "b", "c"))

    # Every progressive draft for one reply shares the same draft_id.
    draft_ids = {d.draft_id for d in bot.drafts}
    assert len(draft_ids) == 1


@pytest.mark.asyncio
async def test_stream_reply_throttles_drafts_by_interval() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    # Flush every token by count, but throttle to one draft per 1.0s.
    gateway = _make_gateway(
        bot, batch_tokens=1, throttle_interval=1.0, clock=clock, sleep=sleep
    )

    await gateway.stream_reply(chat_id=7, tokens=_tokens("x", "y", "z"))

    # The gateway must have slept to honour the interval between drafts.
    assert sleep.durations  # at least one throttle wait happened
    assert all(d <= 1.0 for d in sleep.durations)
    # Final committed text is the full accumulation.
    assert bot.sends[-1].text == "xyz"


@pytest.mark.asyncio
async def test_stream_reply_commits_full_text() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    await gateway.stream_reply(chat_id=7, tokens=_tokens("only"))

    # The completed reply is committed once via send_message.
    assert [s.text for s in bot.sends] == ["only"]


@pytest.mark.asyncio
async def test_stream_reply_backoff_on_rate_limit() -> None:
    bot = _FakeBot(draft_retry_after_on_call=1)
    clock = _FakeClock()
    sleep = _RecordingSleep(clock)
    gateway = _make_gateway(
        bot, batch_tokens=1, throttle_interval=0.0, clock=clock, sleep=sleep
    )

    await gateway.stream_reply(chat_id=7, tokens=_tokens("a", "b"))

    # The first draft hit RetryAfter(3): we slept 3s then retried successfully.
    assert 3 in sleep.durations
    assert bot.drafts[0].text == "a"


@pytest.mark.asyncio
async def test_stream_reply_empty_stream_sends_nothing() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    drafts = await gateway.stream_reply(chat_id=7, tokens=_tokens())

    # Nothing to stream and nothing to commit.
    assert drafts == 0
    assert bot.drafts == []
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
    # The rich path was used — no plain send_message.
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

    # Rich failed → degrade silently to a single plain send_message.
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

    # The plain fallback splits oversized text into limit-sized chunks.
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


# --- Rich streaming: send_rich_message_draft + plain fallback -----------------


@pytest.mark.asyncio
async def test_stream_reply_rich_drafts_then_commits_rich() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=3, throttle_interval=0.0)

    await gateway.stream_reply_rich(chat_id=42, tokens=_tokens("a", "b", "c", "d"))

    # Partial drafts stream as rich drafts; the final reply commits via rich send.
    assert [d.markdown for d in bot.rich_drafts] == ["abc"]
    assert all(d.chat_id == 42 for d in bot.rich_drafts)
    assert len(bot.rich_sends) == 1
    assert bot.rich_sends[0].markdown == "abcd"
    assert bot.sends == []


@pytest.mark.asyncio
async def test_stream_reply_rich_falls_back_to_plain_on_commit_error() -> None:
    bot = _FakeBot(rich_send_raises=True)
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    await gateway.stream_reply_rich(chat_id=7, tokens=_tokens("hi"))

    # Rich commit failed → the finished reply still reaches the user as plain text.
    assert bot.rich_sends == []
    assert len(bot.sends) == 1
    assert bot.sends[0].text == "hi"


@pytest.mark.asyncio
async def test_stream_reply_rich_renders_thinking_on_commit() -> None:
    bot = _FakeBot()
    gateway = _make_gateway(bot, batch_tokens=1, throttle_interval=0.0)

    await gateway.stream_reply_rich(
        chat_id=7, tokens=_tokens("done"), thinking="quick note"
    )

    sent = bot.rich_sends[0].markdown
    assert sent is not None
    assert "quick note" in sent
    assert sent.strip().endswith("done")
