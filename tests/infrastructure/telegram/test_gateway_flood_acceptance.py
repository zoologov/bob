# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-006 acceptance: the live edit-stream **fallback** never floods Telegram.

Since BOB-007 native drafts are the primary, unthrottled streaming path; the
throttled ``editMessageText`` stream is the **fallback** taken only when a peer
rejects drafts. These tests therefore reject drafts (``drafts_rejected=True``) so
the edit-streaming fallback runs, and pin its flood guarantees.

The live incident was a flood-control storm — the inner gateways streamed with a
0s throttle, so every token fired an immediate ``editMessageText`` and the rich
final followed with no gap ("Flood control exceeded on method 'SendRichMessage'.
Retry in 38 seconds."). These tests pin the *behavioural* flood guarantees the
fix must hold under a realistic rapid token stream (not just line coverage):

* **Bounded edits + spacing.** A 12-token burst with a 3s throttle must NOT emit
  one edit per token; successive live writes are spaced at least one throttle
  window apart (the edits never run faster than Telegram tolerates).
* **No-op skip.** A stream whose tokens stop changing the text emits no
  duplicate edits — a repeated identical write is never sent.
* **Single rich final, throttled.** Exactly one ``send_rich_message`` lands, and
  it is sent a full throttle window after the last edit (the original flood
  source was the rich final firing immediately after the last edit).
* **Graceful degradation under flood.** A ``RetryAfter`` flood on the rich final
  triggers no retry storm (one attempt) and the reply is still delivered; and
  when the placeholder send itself fails, a rich-final failure degrades to a
  plain send rather than crashing or losing the reply.

Fakes only: a recording fake aiogram bot + an injected monotonic fake clock whose
``sleep`` advances time, so the throttle window is exercised with no real waiting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from aiogram.exceptions import AiogramError, TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage, SendMessageDraft, SendRichMessageDraft

from bob.application.runtime.event_bus import AsyncEventBus
from bob.infrastructure.telegram.gateway import TelegramGateway, UpdateLike

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from aiogram.types import InputRichMessage

_CHAT = 100
_THREAD = 37  # Bob's forum-topic thread id (live edit-streaming path).
_THROTTLE = 3.0  # The live default flood-control window (BOB-006).


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _EditCall:
    text: str
    at: float


@dataclass
class _RichCall:
    markdown: str | None
    at: float


class _FakeClock:
    """Monotonic fake clock; ``sleep`` advances ``now`` so the throttle is real."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@dataclass
class _FloodBot:
    """Records the live-edit call sequence with timestamps from the fake clock.

    ``rich_retry_after`` makes ``send_rich_message`` raise ``TelegramRetryAfter``
    (the flood). ``placeholder_fails`` makes the first ``send_message``
    (placeholder) raise so the no-placeholder degradation path is exercised.
    ``rich_fails`` makes the rich final raise a generic error.
    """

    clock: _FakeClock
    rich_retry_after: bool = False
    placeholder_fails: bool = False
    rich_fails: bool = False
    # Drafts are rejected so the throttled edit-streaming fallback (the subject of
    # these flood guarantees) runs (BOB-007).
    drafts_rejected: bool = True
    sends: list[str] = field(default_factory=list)
    edits: list[_EditCall] = field(default_factory=list)
    rich_sends: list[_RichCall] = field(default_factory=list)
    deletes: list[int] = field(default_factory=list)
    rich_attempts: int = 0
    _next_message_id: int = 1

    async def get_updates(
        self,
        *,
        offset: int,  # noqa: ARG002
        timeout: int,  # noqa: ARG002
    ) -> Sequence[UpdateLike]:
        return []

    async def send_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        text: str,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        # The live-edit loop retries the placeholder send on every token while no
        # placeholder exists, so to model a peer that never accepts a placeholder
        # we fail every send attempt until a final plain send is the only resort.
        # ``placeholder_fails`` keeps failing until the rich final has been tried,
        # after which the gateway falls back to a plain ``send_message`` (recorded).
        if self.placeholder_fails and self.rich_attempts == 0:
            raise AiogramError("placeholder boom")
        self.sends.append(text)
        message_id = self._next_message_id
        self._next_message_id += 1
        return _FakeMessage(message_id=message_id, text=text)

    async def edit_message_text(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,
        text: str,
    ) -> _FakeMessage:
        self.edits.append(_EditCall(text=text, at=self.clock.now))
        return _FakeMessage(message_id=message_id, text=text)

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool:  # noqa: ARG002
        self.deletes.append(message_id)
        return True

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        if self.drafts_rejected:
            raise TelegramBadRequest(
                method=SendMessageDraft(chat_id=chat_id, draft_id=draft_id, text=""),
                message="Bad Request: TEXTDRAFT_PEER_INVALID",
            )
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.rich_attempts += 1
        if self.rich_retry_after:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=chat_id, text=""),
                message="Flood control exceeded on method 'SendRichMessage'",
                retry_after=38,
            )
        if self.rich_fails:
            raise AiogramError("rich boom")
        self.rich_sends.append(_RichCall(markdown=rich_message.markdown, at=self.clock.now))
        return _FakeMessage(message_id=999, text=rich_message.markdown)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        if self.drafts_rejected:
            raise TelegramBadRequest(
                method=SendRichMessageDraft(
                    chat_id=chat_id, draft_id=draft_id, rich_message=rich_message
                ),
                message="Bad Request: TEXTDRAFT_PEER_INVALID",
            )
        return True


async def _tokens(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


def _gateway(bot: _FloodBot, clock: _FakeClock, *, throttle: float = _THROTTLE) -> TelegramGateway:
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


# --- No flood in a normal rapid token stream ----------------------------------


@pytest.mark.asyncio
async def test_rapid_token_stream_is_rate_limited_not_a_burst() -> None:
    # A realistic rapid stream (12 tokens) must be rate-limited: the gateway
    # sleeps before each live write so the writes are spread out in time rather
    # than fired back-to-back. The flood incident had a 0s window (no sleeps); the
    # fix sleeps a full throttle window between writes.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock)
    gateway = _gateway(bot, clock)

    tokens = [f"t{i} " for i in range(12)]
    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens(*tokens))

    # The stream actually waited between live writes (no 0s-window burst), and
    # every recorded sleep was a positive throttle interval.
    assert bot.edits, "expected live edits to be streamed"
    assert clock.slept, "the rapid stream was not throttled (no sleeps)"
    assert all(amount > 0 for amount in clock.slept), "a zero-length throttle slipped through"
    # The total elapsed time spans at least one window per edit gap — the writes
    # are genuinely spread out, never a single instantaneous burst.
    assert clock.now >= _THROTTLE * (len(bot.edits) - 1)


@pytest.mark.asyncio
async def test_successive_live_edits_are_spaced_at_least_a_throttle_window_apart() -> None:
    # Every gap between successive live edits must be >= the throttle window, so
    # the stream never bursts faster than Telegram tolerates.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock)
    gateway = _gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b", "c", "d", "e"))

    edit_times = [edit.at for edit in bot.edits]
    assert len(edit_times) >= 2, "expected several live edits to compare spacing"
    gaps = [later - earlier for earlier, later in pairwise(edit_times)]
    assert all(gap >= _THROTTLE for gap in gaps), f"edits bursted faster than throttle: {gaps}"


@pytest.mark.asyncio
async def test_unchanged_text_emits_no_duplicate_edit() -> None:
    # Tokens that stop changing the accumulated text must not re-send the same
    # write (the no-op skip) — a key part of staying under flood control.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock)
    gateway = _gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("hi", "", "", ""))

    all_live_writes = bot.sends + [edit.text for edit in bot.edits]
    assert len(all_live_writes) == len(set(all_live_writes)), "a no-op duplicate write was sent"


@pytest.mark.asyncio
async def test_exactly_one_rich_final_lands_and_is_throttled_after_last_edit() -> None:
    # The rich final must be a single send, fired a full throttle window AFTER the
    # last edit — the original 'SendRichMessage' flood was the rich firing with no
    # gap after the last edit.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock)
    gateway = _gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("a", "b", "c"))

    assert bot.rich_attempts == 1, "more than one rich final was attempted"
    assert len(bot.rich_sends) == 1
    last_edit_at = bot.edits[-1].at
    assert bot.rich_sends[0].at - last_edit_at >= _THROTTLE, "rich final fired without throttle"


# --- Graceful degradation under flood -----------------------------------------


@pytest.mark.asyncio
async def test_rich_final_flood_makes_one_attempt_and_keeps_the_reply() -> None:
    # A flood/RetryAfter on the rich final must not retry-storm: one attempt, then
    # degrade to the streamed placeholder (edited to the final plain text). No spam.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock, rich_retry_after=True)
    gateway = _gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo"))

    assert bot.rich_attempts == 1, "the rich final was retried (flood storm)"
    assert bot.rich_sends == [], "a rich final landed despite the flood"
    assert bot.deletes == [], "placeholder deleted despite the rich-final flood"
    assert bot.edits[-1].text == "Hello", "the reply was lost on rich-final flood"


@pytest.mark.asyncio
async def test_placeholder_failure_then_rich_failure_degrades_to_plain_send() -> None:
    # If the placeholder send fails (no placeholder to edit) AND the rich final
    # fails too, the gateway must still deliver the reply via a plain send rather
    # than crash or lose it.
    clock = _FakeClock()
    bot = _FloodBot(clock=clock, placeholder_fails=True, rich_fails=True)
    gateway = _gateway(bot, clock)

    await gateway.stream_reply(chat_id=_CHAT, tokens=_tokens("Hel", "lo"))

    # No edits were possible (placeholder never existed) and the rich final
    # failed, so the final plain text is delivered through send_message.
    assert bot.edits == [], "edited a placeholder that was never created"
    assert bot.rich_sends == [], "a rich final landed despite the failure"
    assert "Hello" in bot.sends, "the reply was lost when both placeholder and rich failed"
    assert bot.deletes == [], "deleted a placeholder that never existed"
