# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure resume policy — what may be raised, and when (BOB-087.D3).

``select_resumable`` is the 🔴 STRUCTURAL guarantee behind «no live-attach»: only a
session on the SAME workspace branch, carrying a non-empty claude session id, in a
TERMINAL state is a candidate — a still-live ``INTERACTIVE`` (or any other non-terminal)
session can never be selected, so two drivers can never end up steering one process.
Among the candidates the FRESHEST by ``updated_at`` wins.

``is_confirmation_fresh`` is the pending-question TTL: a «да» that arrives after the
window (or on a clock that ran backwards) must NOT raise a session. Both are pure,
deterministic, I/O-free — mutation targets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState
from bob.interactive.resume_policy import (
    CONFIRMATION_TTL,
    is_confirmation_fresh,
    select_resumable,
)

_BRANCH = "bob/epic-bob-087"
_OTHER_BRANCH = "bob/epic-other"
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _session(
    *,
    sid: str = "s1",
    branch: str = _BRANCH,
    state: CodingSessionState = CodingSessionState.CANCELLED,
    claude_session_id: str | None = "claude-1",
    updated_at: datetime = _NOW,
) -> CodingSession:
    return CodingSession(
        id=sid,
        task="эпик",
        state=state,
        branch=branch,
        created_at=_NOW - timedelta(days=1),
        updated_at=updated_at,
        claude_session_id=claude_session_id,
    )


# --- select_resumable --------------------------------------------------------


def test_no_sessions_yields_no_candidate() -> None:
    assert select_resumable((), branch=_BRANCH) is None


def test_terminal_session_on_the_branch_is_the_candidate() -> None:
    session = _session()

    assert select_resumable([session], branch=_BRANCH) is session


@pytest.mark.parametrize(
    "state",
    [
        CodingSessionState.CANCELLED,
        CodingSessionState.FAILED,
        CodingSessionState.PR_OPEN,
        CodingSessionState.DONE,
    ],
)
def test_every_terminal_state_is_resumable(state: CodingSessionState) -> None:
    session = _session(state=state)

    assert select_resumable([session], branch=_BRANCH) is session


@pytest.mark.parametrize(
    "state",
    [
        CodingSessionState.INTERACTIVE,  # 🔴 a LIVE session — never attach to it
        CodingSessionState.PROPOSED,
        CodingSessionState.PLANNING,
        CodingSessionState.PLAN_READY,
        CodingSessionState.EXECUTING,
    ],
)
def test_non_terminal_session_is_never_resumable(state: CodingSessionState) -> None:
    # 🔴 No live-attach: a session that is still in flight cannot be picked up, so a
    # resume can never produce a second driver on one claude process.
    assert select_resumable([_session(state=state)], branch=_BRANCH) is None


def test_session_on_another_branch_is_ignored() -> None:
    assert select_resumable([_session(branch=_OTHER_BRANCH)], branch=_BRANCH) is None


@pytest.mark.parametrize("claude_session_id", [None, ""])
def test_session_without_a_claude_session_id_is_ignored(
    claude_session_id: str | None,
) -> None:
    # Without an id there is nothing to pass to ``--resume`` — it is not a candidate.
    session = _session(claude_session_id=claude_session_id)

    assert select_resumable([session], branch=_BRANCH) is None


def test_freshest_by_updated_at_wins() -> None:
    older = _session(sid="old", updated_at=_NOW - timedelta(hours=3))
    newest = _session(sid="new", updated_at=_NOW - timedelta(minutes=5))
    middle = _session(sid="mid", updated_at=_NOW - timedelta(hours=1))

    picked = select_resumable([older, newest, middle], branch=_BRANCH)

    assert picked is newest


def test_freshest_is_chosen_among_candidates_only() -> None:
    # A FRESHER but ineligible session (live / other branch / no id) must not shadow the
    # older genuine candidate — the filter runs before the recency comparison.
    candidate = _session(sid="ok", updated_at=_NOW - timedelta(hours=2))
    live = _session(
        sid="live", state=CodingSessionState.INTERACTIVE, updated_at=_NOW
    )
    foreign = _session(sid="foreign", branch=_OTHER_BRANCH, updated_at=_NOW)
    idless = _session(sid="idless", claude_session_id=None, updated_at=_NOW)

    picked = select_resumable([candidate, live, foreign, idless], branch=_BRANCH)

    assert picked is candidate


# --- is_confirmation_fresh ---------------------------------------------------


def test_confirmation_right_away_is_fresh() -> None:
    assert is_confirmation_fresh(requested_at=_NOW, now=_NOW) is True


def test_confirmation_inside_the_window_is_fresh() -> None:
    asked = _NOW - CONFIRMATION_TTL + timedelta(seconds=1)

    assert is_confirmation_fresh(requested_at=asked, now=_NOW) is True


def test_confirmation_exactly_at_the_ttl_is_still_fresh() -> None:
    # The boundary is inclusive: exactly at the TTL the question is still answerable.
    assert is_confirmation_fresh(requested_at=_NOW - CONFIRMATION_TTL, now=_NOW) is True


def test_confirmation_past_the_ttl_is_stale() -> None:
    asked = _NOW - CONFIRMATION_TTL - timedelta(seconds=1)

    assert is_confirmation_fresh(requested_at=asked, now=_NOW) is False


def test_confirmation_from_the_future_is_stale() -> None:
    # 🔴 A backwards clock must never make a pending question immortal: a negative age
    # is refused rather than trusted.
    assert is_confirmation_fresh(requested_at=_NOW + timedelta(seconds=1), now=_NOW) is False


def test_ttl_is_overridable() -> None:
    asked = _NOW - timedelta(minutes=30)

    assert is_confirmation_fresh(requested_at=asked, now=_NOW, ttl=timedelta(hours=1))
    assert not is_confirmation_fresh(requested_at=asked, now=_NOW, ttl=timedelta(minutes=1))


def test_default_ttl_is_five_minutes() -> None:
    assert timedelta(minutes=5) == CONFIRMATION_TTL
