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
