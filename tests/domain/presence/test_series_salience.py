# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the series-salience plan — batch top-k action budget (BOB-066 Срез W.2).

A pure, deterministic core: given the FOCUS flags of a settled burst (the intake worker's
batch), :func:`plan_series_actions` assigns each message an action — REPLY / REACT / SILENT —
so a burst collapses to ONE addressed reply + a budget-capped like, never N replies. 🔴 A
FOCUS message (direct address) is ALWAYS a REPLY, never dropped by the budget (INV-1).
"""

from __future__ import annotations

from bob.presence.series_salience import SeriesAction, plan_series_actions


def test_every_focus_message_is_answered() -> None:
    # 🔴 INV-1: a direct address is always a REPLY, never capped by the series budget.
    plan = plan_series_actions([True, True], max_reactions=1)

    assert plan == (SeriesAction.REPLY, SeriesAction.REPLY)


def test_ambient_burst_collapses_to_one_reply_plus_a_like() -> None:
    # Several ambient messages in a window → ONE addressed reply + one like, the rest silent.
    plan = plan_series_actions([False, False, False, False], max_reactions=1)

    assert plan == (
        SeriesAction.REPLY,
        SeriesAction.REACT,
        SeriesAction.SILENT,
        SeriesAction.SILENT,
    )


def test_focus_present_means_no_extra_ambient_reply() -> None:
    # A focused message is answered; the ambient ones around it collapse to a like / silence —
    # Bob already engaged the person addressing him, so he does not ALSO barge into the chatter.
    plan = plan_series_actions([False, True, False], max_reactions=1)

    assert plan == (SeriesAction.REACT, SeriesAction.REPLY, SeriesAction.SILENT)


def test_reaction_budget_caps_the_number_of_likes() -> None:
    # The reaction budget is per-series: at most ``max_reactions`` likes land in one burst.
    plan = plan_series_actions([False, False, False], max_reactions=2)

    assert plan == (SeriesAction.REPLY, SeriesAction.REACT, SeriesAction.REACT)


def test_reaction_budget_is_exhausted_not_reset_each_like() -> None:
    # The spent-likes counter ACCUMULATES: with a budget of 2 and four ambient messages, exactly
    # two likes land and the fourth falls silent (a per-like reset would over-like the burst).
    plan = plan_series_actions([False, False, False, False], max_reactions=2)

    assert plan == (
        SeriesAction.REPLY,
        SeriesAction.REACT,
        SeriesAction.REACT,
        SeriesAction.SILENT,
    )


def test_zero_reaction_budget_leaves_only_the_reply() -> None:
    plan = plan_series_actions([False, False, False], max_reactions=0)

    assert plan == (SeriesAction.REPLY, SeriesAction.SILENT, SeriesAction.SILENT)


def test_single_message_replies() -> None:
    assert plan_series_actions([False], max_reactions=1) == (SeriesAction.REPLY,)
    assert plan_series_actions([True], max_reactions=1) == (SeriesAction.REPLY,)


def test_empty_batch_is_empty_plan() -> None:
    assert plan_series_actions([], max_reactions=1) == ()


def test_all_focus_never_drops_any_even_over_budget() -> None:
    # 🔴 INV-1 holds no matter how many direct addresses arrive at once — none is ever a like.
    plan = plan_series_actions([True, True, True], max_reactions=0)

    assert plan == (SeriesAction.REPLY, SeriesAction.REPLY, SeriesAction.REPLY)
