# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Regression: draft streaming is best-effort; the final reply always lands (BOB-004).

The live bug (first two-bot run): when Bob replies in a supergroup forum topic, the
native draft channel (``send_message_draft`` / ``send_rich_message_draft``) is
rejected by Telegram with ``TelegramBadRequest: TEXTDRAFT_PEER_INVALID`` — drafts
are not valid for that peer. Receiving + routing are fine; only the draft-based send
fails. Previously the plain ``stream_reply`` path caught only ``TelegramRetryAfter``,
so the ``TelegramBadRequest`` propagated and the turn delivered *no* reply.

These tests pin the contract with the **real** ``aiogram.exceptions.TelegramBadRequest``
(constructed as aiogram does, with a bound method and the live error message):

* a draft that raises ``TEXTDRAFT_PEER_INVALID`` does **not** escape the reply path;
* the finished reply is still delivered via the non-draft final send, pinned to the
  correct ``message_thread_id`` (Bob's topic);
* once a chat rejects a draft, the rest of the turn stops attempting drafts;
* the happy path (drafts accepted) still streams partials *and* commits the final.
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
    """The real aiogram error Telegram raises for a draft on an invalid peer."""
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
class _RichCall:
    chat_id: int
    markdown: str | None
    message_thread_id: int | None


@dataclass
class _FakeBot:
    """Fake aiogram bot whose drafts can be scripted to reject the peer.

    With ``drafts_rejected`` set, *every* draft call (plain or rich) raises the real
    ``TEXTDRAFT_PEER_INVALID`` ``TelegramBadRequest`` — reproducing a forum-topic peer
    that does not accept drafts. Non-draft sends always succeed and are recorded with
    their ``message_thread_id`` so the test can assert the reply lands in Bob's thread.
    """

    drafts_rejected: bool = False
    sends: list[_SendCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    draft_attempts: int = 0
    rich_draft_attempts: int = 0

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
        return _FakeMessage(message_id=1, text=text, message_thread_id=message_thread_id)

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
        self.draft_attempts += 1
        if self.drafts_rejected:
            raise _peer_invalid_draft()
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        self.rich_sends.append(
            _RichCall(
                chat_id=chat_id,
                markdown=rich_message.markdown,
                message_thread_id=message_thread_id,
            )
        )
        return _FakeMessage(message_id=1, text=rich_message.markdown)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        self.rich_draft_attempts += 1
        if self.drafts_rejected:
            raise _peer_invalid_rich_draft(rich_message)
        return True


async def _zero_sleep(_seconds: float) -> None:
    return None


def _zero_clock() -> float:
    return 0.0


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _gateway(bot: _FakeBot) -> TelegramGateway:
    return TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        batch_tokens=1,
        throttle_interval=0.0,
        clock=_zero_clock,
        sleep=_zero_sleep,
        reply_thread_id=_THREAD,
    )


def _dm_gateway(bot: _FakeBot) -> TelegramGateway:
    """A DM gateway (no thread): the native-draft path the plain regressions cover.

    Drafts are private-chat only (in a topic the gateway types via edit-streaming),
    so BOB-004's draft best-effort contract lives on the DM path.
    """
    return TelegramGateway(
        bot=bot,
        bus=AsyncEventBus(),
        poll_timeout=10,
        batch_tokens=1,
        throttle_interval=0.0,
        clock=_zero_clock,
        sleep=_zero_sleep,
        reply_thread_id=None,
    )


# --- The live bug: TEXTDRAFT_PEER_INVALID on the plain path -------------------


@pytest.mark.asyncio
async def test_plain_draft_peer_invalid_still_delivers_final() -> None:
    # The DM draft path (stream_reply with no thread): a peer rejects drafts. The
    # exception must not escape, and the finished reply must still be committed.
    bot = _FakeBot(drafts_rejected=True)
    gateway = _dm_gateway(bot)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("hel", "lo"))

    assert bot.sends, "the finished reply was not delivered after a draft rejection"
    final = bot.sends[-1]
    assert final.text == "hello"
    assert final.message_thread_id is None


@pytest.mark.asyncio
async def test_plain_draft_rejection_stops_further_draft_attempts() -> None:
    # Once a chat rejects a draft, the rest of the turn should not keep hammering the
    # draft channel — a single rejected attempt is enough to give up on drafts.
    bot = _FakeBot(drafts_rejected=True)
    gateway = _dm_gateway(bot)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b", "c"))

    assert bot.draft_attempts == 1
    assert bot.sends[-1].text == "abc"


# --- The live bug on the rich path -------------------------------------------


@pytest.mark.asyncio
async def test_rich_draft_peer_invalid_still_delivers_final_in_thread() -> None:
    bot = _FakeBot(drafts_rejected=True)
    gateway = _gateway(bot)

    await gateway.stream_reply_rich(chat_id=_CHAT, tokens=_tokens("hel", "lo"))

    assert bot.rich_sends, "the finished rich reply was not delivered"
    final = bot.rich_sends[-1]
    assert final.message_thread_id == _THREAD


@pytest.mark.asyncio
async def test_rich_draft_rejection_stops_further_draft_attempts() -> None:
    bot = _FakeBot(drafts_rejected=True)
    gateway = _gateway(bot)

    await gateway.stream_reply_rich(chat_id=_CHAT, tokens=_tokens("a", "b", "c"))

    assert bot.rich_draft_attempts == 1
    assert bot.rich_sends


# --- Happy path stays intact: drafts stream AND the final commits -------------


@pytest.mark.asyncio
async def test_plain_happy_path_streams_drafts_and_commits_final() -> None:
    bot = _FakeBot(drafts_rejected=False)
    gateway = _dm_gateway(bot)

    drafts = await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b"))

    assert drafts == 2
    assert bot.draft_attempts == 2
    assert bot.sends[-1].text == "ab"
    assert bot.sends[-1].message_thread_id is None


@pytest.mark.asyncio
async def test_rich_happy_path_streams_drafts_and_commits_final() -> None:
    bot = _FakeBot(drafts_rejected=False)
    gateway = _gateway(bot)

    drafts = await gateway.stream_reply_rich(chat_id=_CHAT, tokens=_tokens("a", "b"))

    assert drafts == 2
    assert bot.rich_draft_attempts == 2
    assert bot.rich_sends[-1].message_thread_id == _THREAD
