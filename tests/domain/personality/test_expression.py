# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ExpressionPlan decider (BOB-018, dev wave 1).

``decide_expression`` is a pure, deterministic decider: given a mood, the
per-turn signals, an injected seeded RNG, and small configurable frequencies, it
chooses a *mode* (full reply vs. a terse react-only turn) plus the rare add-on
flags (leak inner life / callback) and a soft form hint. The contract pinned
here is structural and behavioural — determinism under a fixed seed, the
state-driven shift toward terse/REACT_ONLY on low energy + short inbound, and
the anti-tic guarantee that the rare flags stay rare by default — never the exact
internal thresholds (those are free to evolve).
"""

from __future__ import annotations

from random import Random

from bob.domain.personality.expression import (
    ExpressionFreqs,
    ExpressionMode,
    ExpressionPlan,
    ExpressionSignals,
    FormHint,
    decide_expression,
)
from bob.domain.personality.mood import Mood


def _calm() -> Mood:
    """A neutral, middling-energy mood (no strong pull either way)."""
    return Mood()


def _low_energy() -> Mood:
    """Low arousal + withdrawn social — the terse/react-leaning state."""
    return Mood(valence=-0.4, arousal=-0.7, social=-0.6)


def _bright() -> Mood:
    """High arousal + open + social — the expansive-leaning state."""
    return Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6)


def _signals(
    text: str = "расскажи подробнее про это", *, idle_seconds: float = 0.0
) -> ExpressionSignals:
    return ExpressionSignals(inbound_text=text, idle_seconds=idle_seconds)


def test_plan_is_deterministic_under_a_fixed_seed() -> None:
    # Same mood + signals + seed → byte-identical plan, every time.
    plan_a = decide_expression(_bright(), _signals(), rng=Random(42), freqs=ExpressionFreqs())
    plan_b = decide_expression(_bright(), _signals(), rng=Random(42), freqs=ExpressionFreqs())
    assert plan_a == plan_b


def test_plan_carries_all_seam_fields_for_later_beads() -> None:
    # The plan is the seam bob-c4w.2/.3 consume: mode + both rare flags + form.
    plan = decide_expression(_calm(), _signals(), rng=Random(0), freqs=ExpressionFreqs())
    assert isinstance(plan, ExpressionPlan)
    assert plan.mode in (ExpressionMode.REPLY, ExpressionMode.REACT_ONLY)
    assert isinstance(plan.leak_inner_life, bool)
    assert isinstance(plan.callback, bool)
    assert plan.form_hint in (FormHint.TERSE, FormHint.NORMAL, FormHint.EXPANSIVE)


def test_low_energy_short_inbound_leans_terse() -> None:
    # Low arousal + a short inbound → the form hint pulls terse (state-driven).
    plan = decide_expression(
        _low_energy(), _signals("ок", idle_seconds=0.0), rng=Random(1), freqs=ExpressionFreqs()
    )
    assert plan.form_hint is FormHint.TERSE


def test_bright_mood_long_inbound_can_expand() -> None:
    # High arousal/openness + a substantive inbound → form hint allows expansive.
    plan = decide_expression(
        _bright(),
        _signals("расскажи подробно, как это устроено и почему так вышло", idle_seconds=0.0),
        rng=Random(3),
        freqs=ExpressionFreqs(),
    )
    assert plan.form_hint is FormHint.EXPANSIVE


def test_low_energy_short_inbound_leans_react_only_over_a_seed_sweep() -> None:
    # Anti-tic the other way: a withdrawn, low-energy state on a trivial inbound
    # should produce at least SOME react-only turns across seeds (state raises the
    # react chance), where a bright/substantive turn never does (below).
    react = sum(
        decide_expression(
            _low_energy(), _signals("угу"), rng=Random(seed), freqs=ExpressionFreqs()
        ).mode
        is ExpressionMode.REACT_ONLY
        for seed in range(200)
    )
    assert react > 0


def test_substantive_turn_is_never_react_only() -> None:
    # A real, substantive inbound always earns a full REPLY — react-only is for
    # the low-signal/low-energy case, never for a question that wants an answer.
    for seed in range(200):
        plan = decide_expression(
            _bright(),
            _signals("расскажи подробно, как именно это работает внутри"),
            rng=Random(seed),
            freqs=ExpressionFreqs(),
        )
        assert plan.mode is ExpressionMode.REPLY


def test_rare_flags_are_rare_by_default() -> None:
    # Anti-tic: with the small default frequencies, leak/callback fire on only a
    # small fraction of turns across a seed sweep (not on every message).
    n = 400
    leaks = 0
    callbacks = 0
    for seed in range(n):
        plan = decide_expression(_calm(), _signals(), rng=Random(seed), freqs=ExpressionFreqs())
        leaks += plan.leak_inner_life
        callbacks += plan.callback
    assert 0 < leaks < n // 3, f"leak fired {leaks}/{n} — not rare"
    assert 0 < callbacks < n // 3, f"callback fired {callbacks}/{n} — not rare"


def test_zero_frequency_disables_a_flag_entirely() -> None:
    # A frequency of 0 is a hard off switch — the flag never fires (config control).
    off = ExpressionFreqs(leak_inner_life=0.0, callback=0.0)
    for seed in range(200):
        plan = decide_expression(_calm(), _signals(), rng=Random(seed), freqs=off)
        assert plan.leak_inner_life is False
        assert plan.callback is False


def test_higher_frequency_fires_a_flag_more_often() -> None:
    # The frequency monotonically controls rarity: a larger value fires more often.
    def count_leaks(freq: float) -> int:
        f = ExpressionFreqs(leak_inner_life=freq)
        return sum(
            decide_expression(_calm(), _signals(), rng=Random(seed), freqs=f).leak_inner_life
            for seed in range(300)
        )

    assert count_leaks(0.5) > count_leaks(0.05)


def test_freqs_rejects_out_of_range_values() -> None:
    # Frequencies are probabilities — guard the [0, 1] contract at construction.
    for bad in (-0.1, 1.1):
        try:
            ExpressionFreqs(leak_inner_life=bad)
        except ValueError:
            continue
        raise AssertionError(f"frequency {bad} should have been rejected")
