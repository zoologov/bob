# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the backlog catch-up scorer/selector — the pure «rank the backlog» core.

When Bob re-enters a chat after an away period, he does NOT reply to every message that
piled up. He weighs the backlog ONCE and acts on the top of it under a budget. The order
is load-bearing: a message that addressed HIM directly always outranks a reply in his
thread, which always outranks ambient chatter — regardless of how fresh or salient the
ambient is. Within a band, a fresher message beats a merely more-salient one. This pure
core (:func:`score` / :func:`select_catchup`) pins that order deterministically and is
hardened by mutation; 🔴 a focal (direct-address) message is NEVER collapsed out of the
plan, only peripheral ambient beyond budget is (INV-1/INV-10).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bob.presence.catchup import (
    BacklogMessage,
    BacklogScorer,
    CatchUpPlan,
    rank,
    score,
    select_catchup,
)

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def _msg(
    *,
    addressed_to_bob: bool = False,
    reply_to_bob_thread: bool = False,
    salience: float = 0.0,
    age_hours: float = 0.0,
    sender_id: int = 7,
    text: str = "сообщение",
) -> BacklogMessage:
    return BacklogMessage(
        sender_id=sender_id,
        text=text,
        addressed_to_bob=addressed_to_bob,
        reply_to_bob_thread=reply_to_bob_thread,
        salience=salience,
        at=_NOW - timedelta(hours=age_hours),
    )


# ── score: banded priority (direct > reply-thread > ambient) ─────────────────────


def test_direct_address_outranks_reply_thread() -> None:
    # Arrange: a direct address vs a reply in Bob's thread.
    direct = _msg(addressed_to_bob=True)
    reply = _msg(reply_to_bob_thread=True)

    # Act / Assert: the band gap is absolute.
    assert score(direct, now=_NOW) > score(reply, now=_NOW)


def test_reply_thread_outranks_ambient() -> None:
    reply = _msg(reply_to_bob_thread=True)
    ambient = _msg()

    assert score(reply, now=_NOW) > score(ambient, now=_NOW)


def test_direct_address_outranks_stale_low_salience_but_the_band_holds() -> None:
    # A direct address that is OLD and dull still outranks the freshest, most salient
    # ambient — the band never crosses (this is the focal guarantee at score level).
    direct_old_dull = _msg(addressed_to_bob=True, salience=0.0, age_hours=48.0)
    ambient_fresh_hot = _msg(salience=1.0, age_hours=0.0)

    assert score(direct_old_dull, now=_NOW) > score(ambient_fresh_hot, now=_NOW)


def test_reply_thread_outranks_freshest_hottest_ambient() -> None:
    reply_old_dull = _msg(reply_to_bob_thread=True, salience=0.0, age_hours=48.0)
    ambient_fresh_hot = _msg(salience=1.0, age_hours=0.0)

    assert score(reply_old_dull, now=_NOW) > score(ambient_fresh_hot, now=_NOW)


# ── score: within a band, freshness dominates salience ───────────────────────────


def test_fresher_beats_more_salient_within_band() -> None:
    # Same band (ambient); freshness must outweigh salience.
    fresh_dull = _msg(salience=0.0, age_hours=0.0)
    stale_hot = _msg(salience=1.0, age_hours=48.0)

    assert score(fresh_dull, now=_NOW) > score(stale_hot, now=_NOW)


def test_fresher_scores_higher_than_older_all_else_equal() -> None:
    fresh = _msg(age_hours=0.0)
    older = _msg(age_hours=5.0)

    assert score(fresh, now=_NOW) > score(older, now=_NOW)


def test_more_salient_scores_higher_when_equally_fresh() -> None:
    hot = _msg(salience=0.9, age_hours=1.0)
    dull = _msg(salience=0.1, age_hours=1.0)

    assert score(hot, now=_NOW) > score(dull, now=_NOW)


def test_future_timestamp_is_treated_as_freshest_not_negative() -> None:
    # Clock skew: a message «from the future» must not out-score a present one nor
    # produce a runaway score — it clamps to maximum freshness (age 0).
    future = _msg(age_hours=-3.0)
    present = _msg(age_hours=0.0)

    assert score(future, now=_NOW) == score(present, now=_NOW)


def test_salience_is_clamped_into_unit_range() -> None:
    # Out-of-range salience must not let an ambient message climb into a higher band.
    absurd_ambient = _msg(salience=10.0, age_hours=0.0)
    reply = _msg(reply_to_bob_thread=True, salience=0.0, age_hours=48.0)

    assert score(reply, now=_NOW) > score(absurd_ambient, now=_NOW)


def test_negative_salience_is_clamped_to_zero() -> None:
    negative = _msg(salience=-5.0, age_hours=1.0)
    zero = _msg(salience=0.0, age_hours=1.0)

    assert score(negative, now=_NOW) == score(zero, now=_NOW)


def test_salience_above_one_is_clamped_to_one() -> None:
    # A salience of 1.5 must weigh exactly as 1.0 — the clamp caps at the top of the band.
    above = _msg(salience=1.5, age_hours=1.0)
    one = _msg(salience=1.0, age_hours=1.0)

    assert score(above, now=_NOW) == score(one, now=_NOW)


def test_score_has_the_exact_banded_value() -> None:
    # Pin the exact arithmetic: ambient band 0.0 + freshness 0.6·(1/(1+1h)) + salience
    # 0.3·0.5 = 0.6·0.5 + 0.15 = 0.45. Any change to the recency curve or the weights
    # shifts this number.
    ambient = _msg(salience=0.5, age_hours=1.0)

    assert score(ambient, now=_NOW) == pytest.approx(0.45)


def test_direct_band_adds_exactly_two() -> None:
    # The same message at the direct band scores exactly 2.0 higher than ambient — the
    # band floor is a fixed whole-number offset.
    ambient = _msg(salience=0.5, age_hours=1.0)
    direct = _msg(addressed_to_bob=True, salience=0.5, age_hours=1.0)

    assert score(direct, now=_NOW) - score(ambient, now=_NOW) == pytest.approx(2.0)


# ── rank: stable descending order ────────────────────────────────────────────────


def test_rank_orders_by_score_descending() -> None:
    ambient = _msg(text="ambient")
    reply = _msg(reply_to_bob_thread=True, text="reply")
    direct = _msg(addressed_to_bob=True, text="direct")

    ranked = rank((ambient, direct, reply), now=_NOW)

    assert [m.text for m in ranked] == ["direct", "reply", "ambient"]


def test_rank_is_stable_for_ties() -> None:
    first = _msg(text="a", age_hours=1.0)
    second = _msg(text="b", age_hours=1.0)

    ranked = rank((first, second), now=_NOW)

    # Equal score → input order preserved (stable sort).
    assert [m.text for m in ranked] == ["a", "b"]


# ── select_catchup: one pass, budget, focal never collapses ──────────────────────


def test_one_pass_answers_direct_and_collapses_excess_ambient() -> None:
    # A direct question plus a flood of ambient, budget of two: the direct is answered
    # and only the two freshest ambient ride along; the rest collapse.
    direct = _msg(addressed_to_bob=True, text="direct")
    ambient = tuple(
        _msg(text=f"ambient-{i}", age_hours=float(i)) for i in range(5)
    )

    plan = select_catchup((direct, *ambient), now=_NOW, budget=2)

    assert direct in plan.to_answer
    # Budget 2 minus the 1 focal leaves one peripheral slot → freshest ambient only.
    assert [m.text for m in plan.to_answer] == ["direct", "ambient-0"]
    assert {m.text for m in plan.collapsed} == {
        "ambient-1",
        "ambient-2",
        "ambient-3",
        "ambient-4",
    }


def test_budget_caps_ambient_count_exactly() -> None:
    # No focal at all: a budget of two keeps exactly the two freshest ambient and
    # collapses the rest — the ambient counter must advance by exactly one per kept slot.
    ambient = tuple(_msg(text=f"ambient-{i}", age_hours=float(i)) for i in range(4))

    plan = select_catchup(ambient, now=_NOW, budget=2)

    assert [m.text for m in plan.to_answer] == ["ambient-0", "ambient-1"]
    assert [m.text for m in plan.collapsed] == ["ambient-2", "ambient-3"]


def test_focal_is_never_collapsed_even_past_budget() -> None:
    # More direct addresses than the whole budget: EVERY direct is still answered,
    # only ambient collapses. This is the load-bearing INV-1/INV-10 guarantee.
    directs = tuple(
        _msg(addressed_to_bob=True, text=f"direct-{i}") for i in range(4)
    )
    ambient = _msg(text="ambient")

    plan = select_catchup((*directs, ambient), now=_NOW, budget=1)

    assert {m.text for m in plan.to_answer} == {
        "direct-0",
        "direct-1",
        "direct-2",
        "direct-3",
    }
    assert [m.text for m in plan.collapsed] == ["ambient"]


def test_zero_budget_still_answers_focal_drops_all_ambient() -> None:
    direct = _msg(addressed_to_bob=True, text="direct")
    ambient = _msg(text="ambient")

    plan = select_catchup((direct, ambient), now=_NOW, budget=0)

    assert [m.text for m in plan.to_answer] == ["direct"]
    assert [m.text for m in plan.collapsed] == ["ambient"]


def test_negative_budget_is_treated_as_zero_ambient() -> None:
    direct = _msg(addressed_to_bob=True, text="direct")
    ambient = _msg(text="ambient")

    plan = select_catchup((direct, ambient), now=_NOW, budget=-3)

    assert [m.text for m in plan.to_answer] == ["direct"]
    assert [m.text for m in plan.collapsed] == ["ambient"]


def test_budget_covers_all_when_generous() -> None:
    msgs = (
        _msg(addressed_to_bob=True, text="direct"),
        _msg(reply_to_bob_thread=True, text="reply"),
        _msg(text="ambient"),
    )

    plan = select_catchup(msgs, now=_NOW, budget=10)

    assert [m.text for m in plan.to_answer] == ["direct", "reply", "ambient"]
    assert plan.collapsed == ()


def test_empty_backlog_yields_empty_plan() -> None:
    plan = select_catchup((), now=_NOW, budget=3)

    assert plan == CatchUpPlan(to_answer=(), collapsed=())


# ── BacklogScorer facade ─────────────────────────────────────────────────────────


def test_scorer_facade_delegates_to_score() -> None:
    scorer = BacklogScorer()
    msg = _msg(addressed_to_bob=True)

    assert scorer.score(msg, now=_NOW) == score(msg, now=_NOW)


def test_scorer_facade_delegates_to_select() -> None:
    scorer = BacklogScorer()
    direct = _msg(addressed_to_bob=True, text="direct")
    ambient = _msg(text="ambient")

    assert scorer.select((direct, ambient), now=_NOW, budget=1) == select_catchup(
        (direct, ambient), now=_NOW, budget=1
    )
