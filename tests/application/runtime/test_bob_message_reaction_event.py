# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the BOB-050 ``BobMessageReaction`` application event."""

from __future__ import annotations

from bob.kernel.events import (
    BOB_MESSAGE_REACTION,
    BobMessageReaction,
)


def test_event_carries_diff_and_reactor() -> None:
    event = BobMessageReaction(
        chat_id=100,
        message_id=42,
        emoji_added=("❤️",),
        emoji_removed=("👍",),
        reactor_sender_id=777,
        reactor_name="Ada",
    )

    assert event.chat_id == 100
    assert event.message_id == 42
    assert event.emoji_added == ("❤️",)
    assert event.emoji_removed == ("👍",)
    assert event.reactor_sender_id == 777
    assert event.reactor_name == "Ada"


def test_event_name_is_stable_for_bus_routing() -> None:
    event = BobMessageReaction(chat_id=1, message_id=2)
    assert event.name == BOB_MESSAGE_REACTION


def test_anonymous_event_defaults_have_no_reactor() -> None:
    # The defensive "someone reacted" signal: no per-user attribution.
    event = BobMessageReaction(chat_id=1, message_id=2, emoji_added=("🔥",))
    assert event.reactor_sender_id is None
    assert event.reactor_name is None
    assert event.emoji_removed == ()
