# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`~bob.application.usecases.catch_up.CatchUp` — one re-entry pass.

The use-case is the application collaborator over the pure catch-up core (BOB-066 3.2). It
projects the away-period backlog (runtime ``MessageReceived`` events peeked from the intake
buffer) onto the presence domain's value-shaped :class:`~bob.presence.catchup.BacklogMessage`,
runs ONE :func:`~bob.presence.catchup.select_catchup` pass under an action budget, and folds
in the :func:`~bob.personality.absence.absence_hint` re-entry tone. Behaviour-changing, so it
ships behind a flag that is OFF by default — disabled, it degrades to «no catch-up» (an empty
plan), exactly the current behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.application.usecases.catch_up import CatchUp, CatchUpOutcome, to_backlog_message
from bob.kernel.events import MessageReceived
from bob.presence.catchup import BacklogMessage

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)
_BOB_USER_ID = 100


def _event(
    *,
    update_id: int,
    mentions_bob: bool = False,
    reply_to_sender_id: int | None = None,
    sender_id: int = 7,
    text: str = "сообщение",
) -> MessageReceived:
    return MessageReceived(
        update_id=update_id,
        chat_id=1,
        message_id=update_id,
        text=text,
        sender_id=sender_id,
        reply_to_sender_id=reply_to_sender_id,
        mentions_bob=mentions_bob,
    )


def _backlog(
    *,
    addressed_to_bob: bool = False,
    reply_to_bob_thread: bool = False,
    salience: float = 0.0,
    age_hours: float = 0.0,
    text: str = "сообщение",
) -> BacklogMessage:
    return BacklogMessage(
        sender_id=7,
        text=text,
        addressed_to_bob=addressed_to_bob,
        reply_to_bob_thread=reply_to_bob_thread,
        salience=salience,
        at=_NOW - timedelta(hours=age_hours),
    )


# ── to_backlog_message: project MessageReceived onto the domain VO ───────────────


def test_mention_projects_to_direct_address() -> None:
    event = _event(update_id=1, mentions_bob=True)

    backlog = to_backlog_message(event, bob_user_id=_BOB_USER_ID, at=_NOW, salience=0.2)

    assert backlog.addressed_to_bob is True
    assert backlog.reply_to_bob_thread is False


def test_reply_to_bob_projects_to_direct_address() -> None:
    event = _event(update_id=1, reply_to_sender_id=_BOB_USER_ID)

    backlog = to_backlog_message(event, bob_user_id=_BOB_USER_ID, at=_NOW, salience=0.0)

    assert backlog.addressed_to_bob is True


def test_reply_to_someone_else_in_bob_thread_projects_to_reply_thread() -> None:
    event = _event(update_id=1, reply_to_sender_id=999)

    backlog = to_backlog_message(
        event, bob_user_id=_BOB_USER_ID, at=_NOW, salience=0.0, in_bob_thread=True
    )

    assert backlog.addressed_to_bob is False
    assert backlog.reply_to_bob_thread is True


def test_plain_message_projects_to_ambient() -> None:
    event = _event(update_id=1)

    backlog = to_backlog_message(event, bob_user_id=_BOB_USER_ID, at=_NOW, salience=0.4)

    assert backlog.addressed_to_bob is False
    assert backlog.reply_to_bob_thread is False
    assert backlog.salience == 0.4
    assert backlog.at == _NOW
    assert backlog.sender_id == 7
    assert backlog.text == "сообщение"


def test_direct_address_wins_over_thread_flag() -> None:
    # A mention that also sits in Bob's thread is FOCAL, not merely thread-continuation.
    event = _event(update_id=1, mentions_bob=True, reply_to_sender_id=999)

    backlog = to_backlog_message(
        event, bob_user_id=_BOB_USER_ID, at=_NOW, salience=0.0, in_bob_thread=True
    )

    assert backlog.addressed_to_bob is True
    assert backlog.reply_to_bob_thread is False


# ── CatchUp.plan: the OFF-by-default flag ────────────────────────────────────────


def test_disabled_by_default_returns_empty_plan() -> None:
    catch_up = CatchUp(absence_threshold_hours=6.0)
    backlog = (_backlog(addressed_to_bob=True, text="direct"),)

    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=None, budget=3)

    assert outcome == CatchUpOutcome.empty()
    assert outcome.plan.to_answer == ()
    assert outcome.absence_tone is None


def test_explicitly_disabled_returns_empty_plan() -> None:
    catch_up = CatchUp(enabled=False, absence_threshold_hours=6.0)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=None, budget=3)

    assert outcome.plan.to_answer == ()
    assert outcome.plan.collapsed == ()


# ── CatchUp.plan: enabled — one pass, budget, focal never lost ───────────────────


def test_enabled_answers_focal_and_collapses_excess_ambient() -> None:
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    direct = _backlog(addressed_to_bob=True, text="direct")
    ambient = tuple(_backlog(text=f"ambient-{i}", age_hours=float(i)) for i in range(4))

    outcome = catch_up.plan(
        backlog=(direct, *ambient), now=_NOW, last_seen=None, budget=2
    )

    # One pass: the direct question is answered; only the freshest ambient rides along.
    assert [m.text for m in outcome.plan.to_answer] == ["direct", "ambient-0"]
    assert {m.text for m in outcome.plan.collapsed} == {
        "ambient-1",
        "ambient-2",
        "ambient-3",
    }


def test_enabled_never_drops_focal_even_past_budget() -> None:
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    directs = tuple(_backlog(addressed_to_bob=True, text=f"d-{i}") for i in range(3))
    ambient = _backlog(text="ambient")

    outcome = catch_up.plan(
        backlog=(*directs, ambient), now=_NOW, last_seen=None, budget=1
    )

    assert {m.text for m in outcome.plan.to_answer} == {"d-0", "d-1", "d-2"}
    assert [m.text for m in outcome.plan.collapsed] == ["ambient"]


# ── CatchUp.plan: absence-hint re-entry tone ─────────────────────────────────────


def test_long_gap_yields_absence_tone() -> None:
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    last_seen = _NOW - timedelta(days=2)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(
        backlog=backlog, now=_NOW, last_seen=last_seen, budget=3
    )

    assert outcome.absence_tone == "последний разговор был несколько дней назад"


def test_hours_gap_yields_hours_bucket_absence_tone() -> None:
    # A gap within a day surfaces as an hours-count re-entry note, folded through CatchUp
    # (not just the multi-day bucket) — verifying the bucket routing end-to-end.
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    last_seen = _NOW - timedelta(hours=20)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=last_seen, budget=3)

    assert outcome.absence_tone == "последний разговор был около 20 часов назад"


def test_yesterday_gap_yields_yesterday_bucket_absence_tone() -> None:
    # A gap between one and two days surfaces as the «вчера» bucket through CatchUp.
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    last_seen = _NOW - timedelta(hours=30)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=last_seen, budget=3)

    assert outcome.absence_tone == "последний разговор был вчера"


def test_absence_tone_rides_alongside_the_catch_up_plan() -> None:
    # A long gap folds the re-entry tone in WITHOUT disturbing the one-pass plan — Bob
    # still answers the focal message and the tone is the compose-prompt texture beside it.
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    last_seen = _NOW - timedelta(days=3)
    direct = _backlog(addressed_to_bob=True, text="direct")
    ambient = _backlog(text="ambient")

    outcome = catch_up.plan(
        backlog=(direct, ambient), now=_NOW, last_seen=last_seen, budget=1
    )

    assert [m.text for m in outcome.plan.to_answer] == ["direct"]
    assert outcome.absence_tone == "последний разговор был несколько дней назад"


def test_short_gap_yields_no_absence_tone() -> None:
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    last_seen = _NOW - timedelta(hours=1)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(
        backlog=backlog, now=_NOW, last_seen=last_seen, budget=3
    )

    assert outcome.absence_tone is None


def test_no_last_seen_yields_no_absence_tone() -> None:
    catch_up = CatchUp(enabled=True, absence_threshold_hours=6.0)
    backlog = (_backlog(addressed_to_bob=True),)

    outcome = catch_up.plan(backlog=backlog, now=_NOW, last_seen=None, budget=3)

    assert outcome.absence_tone is None
