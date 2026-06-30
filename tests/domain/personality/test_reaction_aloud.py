# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the being-received acknowledgment hint formatter (BOB-050 .3).

The pure read side of a notable reaction: turn the most-recent
:class:`NotableReaction` into ONE light compose-context HINT Bob may fold in
naturally — never a scripted phrase he must utter.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.domain.personality.reaction_aloud import acknowledgment_hint
from bob.domain.personality.reaction_effect import NotableReaction


def _note() -> NotableReaction:
    return NotableReaction(
        sender_id=7,
        reactor_name="Норман",
        emoji="❤️",
        bob_excerpt="кофе по утрам — это ритуал",
        interpretation="ему откликнулось",
        at=datetime(2026, 6, 30, tzinfo=UTC),
    )


def test_hint_carries_the_reactor_emoji_and_excerpt() -> None:
    line = acknowledgment_hint(_note())

    assert "Норман" in line
    assert "❤️" in line
    assert "кофе по утрам — это ритуал" in line


def test_hint_is_optional_not_a_directive() -> None:
    # It must read as a soft HINT ("если к месту", "не обязательно"), so the reply
    # tier weaves it in or not — never a forced, scripted line.
    line = acknowledgment_hint(_note())

    assert "если к месту" in line
    assert "не обязательно" in line


def test_hint_is_a_single_line() -> None:
    # One compose-context line, never a multi-line block that would dominate the prompt.
    assert "\n" not in acknowledgment_hint(_note())
