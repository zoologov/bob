# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the intake focus predicate (BOB-066 Срез 2.1)."""

from __future__ import annotations

from bob.application.runtime.intake.focus import make_focus_predicate, message_is_focused
from bob.kernel.events import MessageReceived

_BOB_ID = 500


def _msg(
    *,
    text: str = "просто болтаю",
    mentions_bob: bool = False,
    reply_to_sender_id: int | None = None,
) -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=42,
        message_id=7,
        text=text,
        mentions_bob=mentions_bob,
        reply_to_sender_id=reply_to_sender_id,
    )


def test_mention_is_focused() -> None:
    assert message_is_focused(_msg(mentions_bob=True), bob_user_id=_BOB_ID)


def test_reply_to_bob_is_focused() -> None:
    assert message_is_focused(_msg(reply_to_sender_id=_BOB_ID), bob_user_id=_BOB_ID)


def test_name_address_is_focused() -> None:
    assert message_is_focused(_msg(text="Боб, привет"), bob_user_id=_BOB_ID)


def test_ambient_is_not_focused() -> None:
    assert not message_is_focused(_msg(text="Боб классный парень"), bob_user_id=_BOB_ID)


def test_predicate_reads_the_bob_id_lazily() -> None:
    resolved: list[int | None] = [None]
    predicate = make_focus_predicate(lambda: resolved[0])
    reply = _msg(reply_to_sender_id=_BOB_ID)
    # Before identity resolves, a reply-to-Bob cannot be told apart → not yet focused.
    assert not predicate(reply)
    resolved[0] = _BOB_ID
    assert predicate(reply)
