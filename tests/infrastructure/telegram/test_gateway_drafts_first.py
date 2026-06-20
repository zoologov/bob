# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Drafts-first streaming for ALL chats incl. group topics (BOB-007).

Threaded Mode is now ON in BotFather, so native drafts
(``send_message_draft`` / ``send_rich_message_draft``) work in group forum topics
too. Native drafts are therefore the **primary** smooth-streaming path for every
chat — passing ``message_thread_id`` for topic messages, streaming rich blocks +
``RichBlockThinking`` natively, with **no 3s edit throttle** (drafts are the native
streaming mechanism, not edit-spam).

The edit-streaming path (throttled ``editMessageText`` placeholder, then rich/plain
final) is the **fallback**: it engages only when a draft call raises
``TelegramBadRequest`` (e.g. a peer that still rejects drafts with
``TEXTDRAFT_PEER_INVALID``). The 3.0s throttle stays only on that fallback path. The
reply is never lost: draft fails -> edit-stream; edit also fails -> plain send.

No real Telegram network: a fake aiogram bot records every call; a monotonic fake
clock + recording sleep make the fallback throttle deterministic (no real waiting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessageDraft, SendRichMessageDraft

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.gateway import TelegramGateway, UpdateLike

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

_CHAT = 100
_THREAD = 37  # Bob's forum-topic thread id, as in the live incident.

_PEER_INVALID = "Bad Request: TEXTDRAFT_PEER_INVALID"


def _peer_invalid_draft() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessageDraft(chat_id=_CHAT, draft_id=1, text=""),
        message=_PEER_INVALID,
    )


def _peer_invalid_rich_draft(rich_message: InputRichMessage) -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendRichMessageDraft(
            chat_id=_CHAT, draft_id=1, rich_message=rich_message
        ),
        message=_PEER_INVALID,
    )


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
class _RichDraftCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _DraftCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Fake aiogram bot recording the drafts-first call sequence.

    ``drafts_rejected`` makes every draft call (plain or rich) raise the real
    ``TEXTDRAFT_PEER_INVALID`` ``TelegramBadRequest`` — a peer that still refuses
    drafts, forcing the edit-streaming fallback. ``edit_fails`` then makes
    ``edit_message_text`` (and the placeholder send is kept) fail so the final must
    degrade to a plain send.
    """

    drafts_rejected: bool = False
    edit_fails: bool = False
    rich_final_fails: bool = False
    sends: list[_SendCall] = field(default_factory=list)
    edits: list[_EditCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    drafts: list[_DraftCall] = field(default_factory=list)
    rich_drafts: list[_RichDraftCall] = field(default_factory=list)
    deletes: list[int] = field(default_factory=list)
    _next_message_id: int = 1

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
        if self.edit_fails:
            raise ValueError("edit boom")
        self.edits.append(
            _EditCall(chat_id=chat_id, message_id=message_id, text=text)
        )
        return _FakeMessage(message_id=message_id, text=text)

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool:  # noqa: ARG002
        self.deletes.append(message_id)
        return True

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,  # noqa: ARG002
        text: str,
        message_thread_id: int | None = None,
    ) -> bool:
        if self.drafts_rejected:
            raise _peer_invalid_draft()
        self.drafts.append(
            _DraftCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        if self.rich_final_fails:
            raise ValueError("rich final boom")
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
        chat_id: int,
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> bool:
        if self.drafts_rejected:
            raise _peer_invalid_rich_draft(rich_message)
        self.rich_drafts.append(
            _RichDraftCall(
                chat_id=chat_id,
                markdown=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
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
    bot: _FakeBot, clock: _FakeClock, *, throttle: float = 3.0
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
        throttle_interval=3.0,
        clock=clock,
        sleep=clock.sleep,
        reply_thread_id=None,
    )


# --- Primary path: native drafts in a topic (no throttle, no edit-spam) --------


@pytest.mark.asyncio
async def test_topic_streams_via_native_rich_drafts_not_edits() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo ", "world"))

    # Streaming is via native rich drafts pinned to Bob's thread — NOT edit-spam.
    assert bot.rich_drafts, "no native drafts were streamed in the topic"
    assert all(d.message_thread_id == _THREAD for d in bot.rich_drafts)
    assert bot.edits == [], "edit-streaming was used instead of native drafts"
    # No 3s throttle on the primary draft path — it must not sleep between drafts.
    assert clock.slept == [], "the native-draft path was throttled (edit-spam guard)"
    # The finished reply is committed (rich final into the thread).
    assert bot.rich_sends, "the finished reply was not committed"
    assert bot.rich_sends[-1].message_thread_id == _THREAD


@pytest.mark.asyncio
async def test_topic_draft_stream_includes_thinking_block() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(
        chat_id=_CHAT, tokens=_tokens("answer"), thinking="my private reasoning"
    )

    assert bot.rich_sends, "the finished reply was not committed"
    markdown = bot.rich_sends[-1].markdown or ""
    assert "my private reasoning" in markdown


# --- Fallback: draft rejected -> throttled edit-streaming, reply not lost ------


@pytest.mark.asyncio
async def test_topic_draft_rejected_falls_back_to_throttled_edit_streaming() -> None:
    bot = _FakeBot(drafts_rejected=True)
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock, throttle=3.0)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo ", "world"))

    # Drafts were refused, so the gateway fell back to edit-streaming: a placeholder
    # send into the thread, then incremental edits (throttled).
    assert bot.sends, "no placeholder was sent on the edit fallback"
    assert bot.sends[0].message_thread_id == _THREAD
    assert bot.edits, "the edit-streaming fallback did not run"
    # The 3.0s throttle stays ONLY on the fallback edit path.
    assert clock.slept, "the edit fallback was not throttled"
    # The reply is not lost — the rich final lands in the thread.
    assert bot.rich_sends, "the reply was lost after the draft rejection"
    assert bot.rich_sends[-1].message_thread_id == _THREAD


@pytest.mark.asyncio
async def test_topic_draft_and_edit_both_fail_degrades_to_plain_send() -> None:
    bot = _FakeBot(drafts_rejected=True, edit_fails=True, rich_final_fails=True)
    clock = _FakeClock()
    gateway = _topic_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo"))

    # Draft refused, edits raise, rich final raises — the reply MUST still land via a
    # plain send so it is never lost.
    plain = [s for s in bot.sends if s.text == "Hello"]
    assert plain, "the reply was lost when both draft and edit failed"
    assert plain[-1].message_thread_id == _THREAD


# --- DM still streams via native drafts ---------------------------------------


@pytest.mark.asyncio
async def test_dm_streams_via_native_drafts() -> None:
    bot = _FakeBot()
    clock = _FakeClock()
    gateway = _dm_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b"))

    assert bot.rich_drafts, "the DM did not stream via native drafts"
    assert all(d.message_thread_id is None for d in bot.rich_drafts)
    assert bot.edits == [], "the DM used edit-streaming instead of drafts"
    assert clock.slept == [], "the DM draft path was throttled"
    assert bot.rich_sends, "the DM reply was not committed"


@pytest.mark.asyncio
async def test_dm_draft_rejected_falls_back_and_keeps_reply() -> None:
    bot = _FakeBot(drafts_rejected=True)
    clock = _FakeClock()
    gateway = _dm_gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("hel", "lo"))

    # Even in a DM, a draft rejection must not lose the reply.
    delivered = bool(bot.rich_sends) or any(s.text == "hello" for s in bot.sends)
    assert delivered, "the DM reply was lost after a draft rejection"
