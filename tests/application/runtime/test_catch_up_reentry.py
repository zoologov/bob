# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for CatchUpReentry — the re-entry catch-up pass over a worker's batch (BOB-066 W.3).

Given a drained batch, the collaborator decides whether Bob is RE-ENTERING (the gap since he
last handled a message in this chat is at/beyond the absence threshold) and, if so, runs ONE
select_catchup pass: every focal (direct-address) message plus ambient up to the budget is
handled (arrival order preserved), the rest is skimmed. 🔴 INV-1/10: a focal message is never
skimmed. Disabled → the whole batch passes through unchanged (byte-identical).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.application.runtime.catch_up_reentry import CatchUpReentry
from bob.kernel.events import MessageReceived

if TYPE_CHECKING:
    from collections.abc import Sequence

_T0 = datetime(2026, 7, 29, 9, 0, 0, tzinfo=UTC)


class _AdvancingClock:
    """A clock that returns each queued instant in turn (one per ``select`` call)."""

    def __init__(self, *instants: datetime) -> None:
        self._instants = list(instants)

    def now(self) -> datetime:
        return self._instants.pop(0)


def _msg(update_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=update_id,
        chat_id=7,
        message_id=update_id,
        text=f"сообщение {update_id}",
        sender_id=1,
        mentions_bob=mentions_bob,
    )


def _reentry(
    *instants: datetime,
    enabled: bool = True,
    budget: int = 1,
    bob_user_id: int | None = 500,
) -> CatchUpReentry:
    return CatchUpReentry(
        clock=_AdvancingClock(*instants),
        bob_user_id_source=lambda: bob_user_id,
        absence_threshold_hours=4.0,
        budget=budget,
        enabled=enabled,
    )


def _ids(messages: Sequence[MessageReceived]) -> list[int]:
    return [m.update_id for m in messages]


def test_disabled_passes_the_whole_batch_through() -> None:
    reentry = _reentry(_T0, enabled=False)
    batch = [_msg(1), _msg(2, mentions_bob=True), _msg(3)]

    selection = reentry.select(7, batch)

    assert selection.is_reentry is False
    assert _ids(selection.to_handle) == [1, 2, 3]
    assert selection.skipped == ()


def test_short_gap_is_not_a_reentry() -> None:
    # First batch records last-seen; a second batch 1h later is normal flow, not a re-entry.
    reentry = _reentry(_T0, _T0 + timedelta(hours=1))
    reentry.select(7, [_msg(1)])

    selection = reentry.select(7, [_msg(2), _msg(3)])

    assert selection.is_reentry is False
    assert _ids(selection.to_handle) == [2, 3]


def test_first_ever_batch_is_never_a_reentry() -> None:
    # No prior last-seen → nothing to catch up on → passthrough.
    reentry = _reentry(_T0)
    selection = reentry.select(7, [_msg(1), _msg(2)])
    assert selection.is_reentry is False
    assert _ids(selection.to_handle) == [1, 2]


def test_reentry_after_a_long_gap_runs_one_catch_up_pass() -> None:
    # First batch at T0, then a 5h gap → re-entry: the direct address is answered, and with a
    # total budget of 2 one ambient aside rides along; the rest of the ambient is skimmed.
    reentry = _reentry(_T0, _T0 + timedelta(hours=5), budget=2)
    reentry.select(7, [_msg(1)])

    selection = reentry.select(
        7, [_msg(2), _msg(3, mentions_bob=True), _msg(4), _msg(5)]
    )

    assert selection.is_reentry is True
    # The focal (mentions_bob) message is always answered; one ambient slot rides along.
    assert 3 in _ids(selection.to_handle), "the direct address must be answered (INV-1)"
    assert len(selection.to_handle) == 2, "budget 2 → focal + one ambient"
    assert len(selection.skipped) == 2, "the rest of the ambient is skimmed"
    # Arrival order is preserved among the handled slice (INV-5).
    assert _ids(selection.to_handle) == sorted(_ids(selection.to_handle))


def test_reentry_never_skims_a_focal_message_even_at_zero_budget() -> None:
    # 🔴 INV-1: a zero ambient budget still answers every direct address; only ambient collapses.
    reentry = _reentry(_T0, _T0 + timedelta(hours=6), budget=0)
    reentry.select(7, [_msg(1)])

    selection = reentry.select(7, [_msg(2), _msg(3, mentions_bob=True), _msg(4)])

    assert _ids(selection.to_handle) == [3]
    assert set(_ids(selection.skipped)) == {2, 4}


def test_reentry_falls_back_to_passthrough_without_a_bob_id() -> None:
    # Addressivity can't be projected without Bob's id → safe passthrough (no catch-up).
    reentry = _reentry(_T0, _T0 + timedelta(hours=5), bob_user_id=None)
    reentry.select(7, [_msg(1)])

    selection = reentry.select(7, [_msg(2), _msg(3)])

    assert selection.is_reentry is False
    assert _ids(selection.to_handle) == [2, 3]
