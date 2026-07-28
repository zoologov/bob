# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit checks for the fake-gateway recorder (BOB-066 Срез 0, harness verification).

The `.feature` scenarios pin Bob's behaviour *through* :class:`FakeGateway`; this module
guards the boundary recorder itself so those scenarios can trust it. The three observable
modes a scenario asserts on — a **reply**, a **reaction**, and **silence** — plus the
typing seam are each proven here in isolation, so a later slice observing a reaction or an
honest silence is standing on a verified harness, not an assumed one.

The direct-address scenario only ever exercises the rich-reply path; these tests cover the
plain-send, reaction, and silence seams that scenario leaves untouched.
"""

from __future__ import annotations

from datetime import datetime

from tests.acceptance.fake_gateway import FakeGateway, now


class _RichReply:
    """Minimal stand-in for the rich message Bob commits (only ``markdown`` is read)."""

    def __init__(self, markdown: str) -> None:
        self.markdown = markdown


async def test_fresh_gateway_reports_silence() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act — no turn driven.
    # Assert — the recorder honestly reports Bob said nothing.
    assert gateway.replied is False
    assert gateway.last_reply == ""
    assert gateway.reactions == []
    assert gateway.typings == 0


async def test_rich_reply_is_recorded_as_the_observable_reply() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act
    await gateway.send_rich_message(chat_id=42, rich_message=_RichReply("привет"))
    # Assert
    assert gateway.replied is True
    assert gateway.last_reply == "привет"
    assert gateway.sent == [(42, "привет")]


async def test_plain_send_is_recorded_and_becomes_the_last_reply() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act — two sends; the recorder must surface the latest as ``last_reply``.
    await gateway.send_message(chat_id=42, text="первая")
    msg = await gateway.send_message(chat_id=42, text="вторая")
    # Assert
    assert gateway.sent == [(42, "первая"), (42, "вторая")]
    assert gateway.last_reply == "вторая"
    assert msg.message_id == 1


async def test_reaction_is_recorded_without_counting_as_a_reply() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act
    result = await gateway.set_message_reaction(chat_id=42, message_id=7, reaction=object())
    # Assert — a react-only turn is observable as a reaction, and is NOT a spoken reply.
    assert result is True
    assert gateway.reactions == [(42, 7)]
    assert gateway.replied is False
    assert gateway.last_reply == ""


async def test_typing_action_increments_the_typing_counter() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act
    await gateway.send_chat_action(chat_id=42, action="typing")
    await gateway.send_chat_action(chat_id=42, action="typing")
    # Assert
    assert gateway.typings == 2


async def test_get_updates_yields_no_inbound_updates() -> None:
    # Arrange
    gateway = FakeGateway()
    # Act
    updates = await gateway.get_updates(offset=0, timeout=1)
    # Assert — the fake never injects polling traffic; turns are driven explicitly.
    assert list(updates) == []


def test_now_returns_a_timezone_aware_stamp() -> None:
    # Act
    stamp = now()
    # Assert
    assert isinstance(stamp, datetime)
    assert stamp.tzinfo is not None
