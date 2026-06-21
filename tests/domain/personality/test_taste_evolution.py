# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for taste_evolution.reinforce — the pure self-evolution kernel.

A single reflection nudges a taste axis: liking shifts and conviction firms, both
damped by ``(1 - conviction)`` so a settled opinion barely moves (anti-runaway).
All math is pure and deterministic; bounds are clamped hard.
"""

from __future__ import annotations

import pytest

from bob.domain.personality.taste import TasteAxis
from bob.domain.personality.taste_evolution import ALPHA, BETA, reinforce


def test_positive_nudge_raises_value_and_conviction() -> None:
    # Arrange: a mildly-liked, weakly-held axis.
    axis = TasteAxis(name="jazz", value=0.2, conviction=0.1)

    # Act
    evolved = reinforce(axis, nudge=1.0)

    # Assert: both move upward.
    assert evolved.value > axis.value
    assert evolved.conviction > axis.conviction


def test_negative_nudge_lowers_value() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=0.2, conviction=0.1)

    # Act
    evolved = reinforce(axis, nudge=-1.0)

    # Assert: liking drops, conviction still firms (|nudge| drives conviction).
    assert evolved.value < axis.value
    assert evolved.conviction > axis.conviction


def test_value_step_uses_the_documented_formula() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=0.2, conviction=0.1)

    # Act
    evolved = reinforce(axis, nudge=1.0)

    # Assert: value' = value + alpha * nudge * (1 - conviction).
    expected = 0.2 + ALPHA * 1.0 * (1 - 0.1)
    assert evolved.value == pytest.approx(expected)


def test_conviction_step_uses_the_documented_formula() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=0.2, conviction=0.1)

    # Act
    evolved = reinforce(axis, nudge=-1.0)

    # Assert: conviction' = conviction + beta * |nudge| * (1 - conviction).
    expected = 0.1 + BETA * 1.0 * (1 - 0.1)
    assert evolved.conviction == pytest.approx(expected)


def test_high_conviction_shifts_value_less_than_low_conviction() -> None:
    # Arrange: identical axes save for conviction — the anti-runaway invariant.
    weak = TasteAxis(name="jazz", value=0.0, conviction=0.1)
    firm = TasteAxis(name="jazz", value=0.0, conviction=0.9)

    # Act: same nudge applied to both.
    weak_shift = abs(reinforce(weak, nudge=1.0).value - weak.value)
    firm_shift = abs(reinforce(firm, nudge=1.0).value - firm.value)

    # Assert: a settled opinion moves strictly less.
    assert firm_shift < weak_shift


def test_value_is_clamped_to_upper_bound() -> None:
    # Arrange: already near the ceiling, zero conviction so the step is full.
    axis = TasteAxis(name="jazz", value=0.95, conviction=0.0)

    # Act
    evolved = reinforce(axis, nudge=1.0)

    # Assert: never escapes [-1, 1].
    assert evolved.value <= 1.0


def test_value_is_clamped_to_lower_bound() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=-0.95, conviction=0.0)

    # Act
    evolved = reinforce(axis, nudge=-1.0)

    # Assert
    assert evolved.value >= -1.0


def test_conviction_never_exceeds_one() -> None:
    # Arrange: very firm already.
    axis = TasteAxis(name="jazz", value=0.5, conviction=0.999)

    # Act
    evolved = reinforce(axis, nudge=1.0)

    # Assert: asymptotic growth stays within [0, 1].
    assert 0.0 <= evolved.conviction <= 1.0


def test_full_conviction_freezes_the_axis_no_runaway() -> None:
    # Arrange: a maximally-settled opinion — the strongest anti-runaway extreme.
    # At conviction=1.0 the (1 - conviction) damping is zero, so neither value nor
    # conviction may move however hard the nudge pushes (US-3: no drift at extremes).
    axis = TasteAxis(name="jazz", value=0.4, conviction=1.0)

    # Act: a full-strength nudge against a fully-convinced axis.
    evolved = reinforce(axis, nudge=1.0)

    # Assert: a settled opinion is immovable — value and conviction are unchanged.
    assert evolved.value == pytest.approx(0.4)
    assert evolved.conviction == pytest.approx(1.0)


def test_name_and_experience_count_are_preserved() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=0.2, conviction=0.1, experience_count=5)

    # Act
    evolved = reinforce(axis, nudge=1.0)

    # Assert: reinforce touches only value/conviction; the axis identity is intact.
    assert evolved.name == "jazz"
    assert evolved.experience_count == 5
