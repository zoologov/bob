# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Live edit-streaming in a group topic (BOB-004, Variant B).

Native drafts are private-chat only — a supergroup forum topic rejects them with
``TEXTDRAFT_PEER_INVALID``. So in Bob's topic the gateway types "live" GPT-style by
**incremental ``editMessageText``**: send a plain placeholder, edit it with the
accumulating plain text as tokens stream (throttled, respecting
``TelegramRetryAfter``), then commit the **rich** final (``send_rich_message`` —
headings/lists/code/tables/math + ``RichBlockThinking`` when a ``thinking`` is
present) into the thread and **delete the plain placeholder** (Variant B: live text
replaced by the rich final, a minor flicker is expected).

A DM (no ``reply_thread_id``) keeps the native draft path — drafts are best there.

No real Telegram network: a fake aiogram bot records every call. A monotonic fake
clock + recording sleep make the throttle deterministic (no real waiting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import EditMessageText

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.gateway import TelegramGateway, UpdateLike

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

_CHAT = 100
_THREAD = 37  # Bob's forum-topic thread id, as in the live incident.


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _EditCall:
    chat_id: int
    message_id: int
    text: str


@dataclass
class _RichCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _DeleteCall:
    chat_id: int
    message_id: int


@dataclass
class _FakeBot:
    """Fake aiogram bot that records the live-edit call sequence.

    ``rich_fails`` makes ``send_rich_message`` raise so the rich-final fallback is
    exercised. ``edit_retry_after_on_call`` makes the Nth edit raise
    ``TelegramRetryAfter`` to drive the backoff path deterministically.
    """

    rich_fails: bool = False
    edit_retry_after_on_call: int | None = None
    sends: list[_SendCall] = field(default_factory=list)
    edits: list[_EditCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    deletes: list[_DeleteCall] = field(default_factory=list)
    drafts: list[str] = field(default_factory=list)
    _next_message_id: int = 1
    _edit_calls: int = 0

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        message_id = self._next_message_id
        self._next_message_id += 1
        return _FakeMessage(
            message_id=message_id, text=text, message_thread_id=message_thread_id
        )

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> _FakeMessage:
        self._edit_calls += 1
        if self.edit_retry_after_on_call == self._edit_calls:
            self.edit_retry_after_on_call = None
            raise TelegramRetryAfter(
                method=EditMessageText(chat_id=chat_id, message_id=message_id, text=text),
                message="flood",
                retry_after=3,
            )
        self.edits.append(_EditCall(chat_id=chat_id, message_id=message_id, text=text))
        return _FakeMessage(message_id=message_id, text=text)

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool:
        self.deletes.append(_DeleteCall(chat_id=chat_id, message_id=message_id))
        return True

    async def send_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        text: str,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        self.drafts.append(text)
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.rich_fails:
            raise ValueError("rich send boom")
        self.rich_sends.append(
            _RichCall(
                chat_id=chat_id,
                markdown=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        return _FakeMessage(message_id=999, text=rich_message.markdown)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True


class _FakeClock:
    """Monotonic fake clock; advances by the recorded sleeps so throttle is real."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _topic_gateway(
    bot: _FakeBot, clock: _FakeClock, *, throttle: float = 0.0
) -> TelegramGateway:
    return TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        batch_tokens=1,
        throttle_interval=throttle,
        clock=clock,
        sleep=clock.sleep,
        reply_thread_id=_THREAD,
    )


def _dm_gateway(bot: _FakeBot, clock: _FakeClock) -> TelegramGateway:
    return TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        batch_tokens=1,
        throttle_interval=0.0,
        clock=clock,
        sleep=clock.sleep,
        reply_thread_id=None,
    )


# --- Group topic: placeholder -> live edits -> rich final -> delete -----------


@pytest.mark.asyncio
async def test_topic_streams_placeholder_then_edits_then_rich_final_then_deletes() -> (
    None
):
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo ", "world"))

    # A plain placeholder is sent into Bob's thread first.
    assert bot.sends, "no placeholder was sent"
    assert bot.sends[0].message_thread_id == _THREAD
    # Drafts are never used in a topic (they would be rejected by the peer).
    assert bot.drafts == []
    # The placeholder is edited incrementally as tokens stream (multiple edits).
    assert len(bot.edits) >= 2
    assert bot.edits[-1].text == "Hello world"
    # The final is a rich send into the thread, then the placeholder is deleted.
    assert bot.rich_sends, "the rich final was not sent"
    assert bot.rich_sends[-1].message_thread_id == _THREAD
    # The placeholder (first send, id 1) is deleted so the rich final replaces it.
    placeholder_id = bot.edits[0].message_id
    assert _DeleteCall(chat_id=_CHAT, message_id=placeholder_id) in bot.deletes


@pytest.mark.asyncio
async def test_topic_rich_final_includes_thinking_block() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(
        chat_id=_CHAT, tokens=_tokens("answer"), thinking="my private reasoning"
    )

    assert bot.rich_sends, "the rich final was not sent"
    markdown = bot.rich_sends[-1].markdown or ""
    # RichBlockThinking is serialized as a leading collapsible spoiler block.
    assert "my private reasoning" in markdown


@pytest.mark.asyncio
async def test_topic_edits_are_throttled() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock, throttle=0.7)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b", "c", "d"))

    # With a non-zero throttle the gateway must sleep between edits, never spam.
    assert clock.slept, "edits were not throttled"
    assert all(amount > 0 for amount in clock.slept)


@pytest.mark.asyncio
async def test_topic_skips_noop_edit_when_text_unchanged() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    # Empty tokens after the first do not change the accumulated text.
    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("hi", "", ""))

    edit_texts = [edit.text for edit in bot.edits]
    assert edit_texts == sorted(set(edit_texts), key=edit_texts.index)
    assert len(edit_texts) == len(set(edit_texts)), "a no-op edit was sent"


# --- Robustness: retry-after during an edit, rich-final failure ---------------


@pytest.mark.asyncio
async def test_topic_edit_retry_after_backs_off_and_completes() -> None:
    bot = _FakeBot(edit_retry_after_on_call=1)
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo"))

    # The rate-limited edit backed off (slept) and the turn still completed.
    assert clock.slept, "the gateway did not back off on TelegramRetryAfter"
    assert bot.rich_sends, "the reply was lost after a rate-limited edit"


@pytest.mark.asyncio
async def test_topic_rich_final_failure_falls_back_to_plain_and_keeps_placeholder() -> (
    None
):
    bot = _FakeBot(rich_fails=True)
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo"))

    # Rich failed: no rich send recorded, and the reply is not lost — the
    # placeholder is edited to the final plain text (not deleted).
    assert bot.rich_sends == []
    assert bot.deletes == [], "placeholder deleted despite rich-final failure"
    assert bot.edits[-1].text == "Hello"


# --- DM keeps the native draft path -------------------------------------------


@pytest.mark.asyncio
async def test_dm_uses_native_draft_not_edit_streaming() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _dm_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b"))

    # DM streams via native drafts and commits a plain send; never edits.
    assert bot.drafts == ["a", "ab"]
    assert bot.edits == []
    assert bot.deletes == []
    assert bot.sends[-1].text == "ab"
