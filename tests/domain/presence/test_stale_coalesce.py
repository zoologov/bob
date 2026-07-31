# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :func:`coalesce_stale` — the pure queue-level «stay in the present» core (BOB-072).

Before a settled ambient burst is read as one stream, a message the stream has already
overtaken — the SAME identified sender speaking again immediately after (a re-ask /
reformulation) — is marked superseded so Bob does not answer a line the room moved past.
The core is deterministic and conservative: it only drops a message when the very next
message is from the same identified sender; focal is never dropped (INV-1), an
unidentified sender is never coalesced, and a message with another sender interposed
before the same sender speaks again is kept (the topic may have branched — INV-S3).
"""

from __future__ import annotations

from bob.presence.staleness import QueuedAmbient, coalesce_stale


def _q(sender_id: int | None, *, is_focal: bool = False) -> QueuedAmbient:
    return QueuedAmbient(sender_id=sender_id, is_focal=is_focal)


def test_empty_burst_keeps_nothing() -> None:
    assert coalesce_stale([]) == ()


def test_single_message_is_kept() -> None:
    assert coalesce_stale([_q(1)]) == (True,)


def test_distinct_senders_are_all_kept() -> None:
    # No one is overtaken: three different people each hold their own point.
    assert coalesce_stale([_q(1), _q(2), _q(3)]) == (True, True, True)


def test_same_sender_immediately_again_supersedes_the_earlier() -> None:
    # 🔴 The stream overtook the first line: the same person reformulated right after,
    # so only the latest survives into the read (the earlier one is superseded).
    assert coalesce_stale([_q(7), _q(7)]) == (False, True)


def test_run_of_same_sender_keeps_only_the_latest() -> None:
    assert coalesce_stale([_q(7), _q(7), _q(7)]) == (False, False, True)


def test_interposed_other_sender_keeps_the_earlier() -> None:
    # 🔴 Conservative (INV-S3): someone else spoke between A's two lines, so A's first
    # point may still stand — liveness > economy, do NOT drop it.
    assert coalesce_stale([_q(1), _q(2), _q(1)]) == (True, True, True)


def test_trailing_new_sender_is_kept() -> None:
    assert coalesce_stale([_q(7), _q(7), _q(9)]) == (False, True, True)


def test_focal_is_never_superseded() -> None:
    # 🔴 INV-1: a focal message is kept even if the same sender speaks right after.
    assert coalesce_stale([_q(5, is_focal=True), _q(5)]) == (True, True)


def test_unidentified_sender_is_never_coalesced() -> None:
    # Two anonymous messages are NOT the "same sender" — cannot attribute, so keep both.
    assert coalesce_stale([_q(None), _q(None)]) == (True, True)


def test_two_senders_each_reformulating_supersede_independently() -> None:
    # 🔴 Multiple senders in one burst: A re-asks (A,A) and then B re-asks (B,B). Each sender's
    # earlier line is superseded by ITS OWN next line — the coalescing is per-sender-adjacency,
    # not a global "keep the last" — so only each sender's latest survives into the read.
    assert coalesce_stale([_q(1), _q(1), _q(2), _q(2)]) == (False, True, False, True)


def test_a_reformulation_wrapped_around_another_sender_keeps_the_earlier() -> None:
    # A speaks, B interposes, A speaks again: A's first line is KEPT (B branched the topic —
    # not provably overtaken), and B's single line stands. Conservative INV-S3 across senders.
    assert coalesce_stale([_q(1), _q(2), _q(1)]) == (True, True, True)


def test_prior_line_before_a_focal_from_the_same_sender_is_kept() -> None:
    # 🔴 The dual of «focal is never superseded»: when the NEXT slot is a focal from the same
    # sender, the earlier ambient line is NOT dropped — a message is only superseded by a
    # non-focal same-sender follow-up (the `not nxt.is_focal` guard), so the focal never
    # silently swallows the line before it.
    assert coalesce_stale([_q(3), _q(3, is_focal=True)]) == (True, True)


def test_unidentified_then_identified_same_position_is_not_treated_as_same_sender() -> None:
    # An anonymous line followed by an identified one is never coalesced — None is not a
    # provable «same sender» as any id, so both are kept (no false supersede on missing id).
    assert coalesce_stale([_q(None), _q(5)]) == (True, True)
