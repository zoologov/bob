# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the outgoing-target policy (BOB-066 Срез 1.1 — reply-to on the way out).

:func:`resolve_outgoing_target` is the pure conversation-domain core that decides
WHERE Bob's reply lands this turn: at 3+ participants (``others_present``) a reply
QUOTES the addressed message (``reply_to_message_id`` set); in a focal 1:1 it does
NOT (``None`` — the un-quoted, topic-only send that is today's whole behaviour). The
policy is deterministic (no LLM/transport) so it is exhaustively truth-tabled here —
the acceptance layer proves the same contract through the fake gateway.
"""

from __future__ import annotations

import pytest

from bob.conversation.outgoing_target import OutgoingTarget, resolve_outgoing_target

_MESSAGE_ID = 7
_ADDRESSEE_ID = 5


def _resolve(*, others_present: bool, focal_1to1: bool) -> OutgoingTarget:
    return resolve_outgoing_target(
        message_id=_MESSAGE_ID,
        addressee_id=_ADDRESSEE_ID,
        others_present=others_present,
        focal_1to1=focal_1to1,
    )


def test_quotes_when_others_present_and_not_focal_1to1() -> None:
    """3+ participants, not a locked 1:1 → the reply QUOTES the addressed message."""
    target = _resolve(others_present=True, focal_1to1=False)
    assert target.reply_to_message_id == _MESSAGE_ID


def test_does_not_quote_in_focal_1to1_even_with_others_present() -> None:
    """A focal 1:1 suppresses the quote even when a third party is around."""
    target = _resolve(others_present=True, focal_1to1=True)
    assert target.reply_to_message_id is None


def test_does_not_quote_when_alone_1to1() -> None:
    """1:1 (no third participant) → no quote — today's topic-only behaviour, preserved."""
    target = _resolve(others_present=False, focal_1to1=True)
    assert target.reply_to_message_id is None


def test_does_not_quote_on_ambient_1to1() -> None:
    """A 1:1 that is not itself a focal turn still never quotes (no others present)."""
    target = _resolve(others_present=False, focal_1to1=False)
    assert target.reply_to_message_id is None


@pytest.mark.parametrize("focal_1to1", [True, False])
@pytest.mark.parametrize("others_present", [True, False])
def test_addressee_is_always_carried_through(
    *, others_present: bool, focal_1to1: bool
) -> None:
    """The addressee id rides on the target regardless of the quote decision."""
    target = _resolve(others_present=others_present, focal_1to1=focal_1to1)
    assert target.addressee_id == _ADDRESSEE_ID


def test_none_addressee_is_preserved() -> None:
    """An unresolved sender (``None``) is carried through, never invented."""
    target = resolve_outgoing_target(
        message_id=_MESSAGE_ID,
        addressee_id=None,
        others_present=True,
        focal_1to1=False,
    )
    assert target.addressee_id is None
    assert target.reply_to_message_id == _MESSAGE_ID


def test_target_is_an_immutable_value_object() -> None:
    """The VO is frozen — a turn's output target cannot be mutated in place."""
    target = _resolve(others_present=True, focal_1to1=False)
    with pytest.raises(AttributeError):
        target.reply_to_message_id = 99  # type: ignore[misc]


def test_default_target_is_the_legacy_no_quote_send() -> None:
    """A bare ``OutgoingTarget()`` is the legacy send: no quote, no addressee."""
    target = OutgoingTarget()
    assert target.reply_to_message_id is None
    assert target.addressee_id is None
