# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``reply_delay_inputs`` — the pure demand/interest → (complexity, urgency) map.

The one wiring-decision core of the DelayedTurn hookup (BOB-066 Срез W): it turns the
existing ``classify_answer_demand`` verdict + Bob's topic interest into the two ``[0, 1]``
knobs the pure :class:`~bob.presence.natural_delay.NaturalDelayPolicy` reads. Deterministic,
no clock/rng — the mutation target of this slice.
"""

from __future__ import annotations

import pytest

from bob.application.usecases.reply_rhythm import reply_delay_inputs
from bob.conversation.brevity import AnswerDemand


def test_high_demand_is_maximally_urgent() -> None:
    _complexity, urgency = reply_delay_inputs(AnswerDemand.HIGH, interest=0.0)
    assert urgency == 1.0


def test_low_demand_is_not_urgent() -> None:
    _complexity, urgency = reply_delay_inputs(AnswerDemand.LOW, interest=0.0)
    assert urgency == 0.0


def test_medium_demand_is_mid_urgency() -> None:
    _complexity, urgency = reply_delay_inputs(AnswerDemand.MEDIUM, interest=0.0)
    assert urgency == pytest.approx(0.5)


def test_urgency_rises_monotonically_with_demand() -> None:
    low = reply_delay_inputs(AnswerDemand.LOW, interest=0.5)[1]
    medium = reply_delay_inputs(AnswerDemand.MEDIUM, interest=0.5)[1]
    high = reply_delay_inputs(AnswerDemand.HIGH, interest=0.5)[1]
    assert low < medium < high


def test_complexity_blends_demand_and_interest() -> None:
    # HIGH demand (weight 1.0) with full interest → a fully complex, deep reply.
    assert reply_delay_inputs(AnswerDemand.HIGH, interest=1.0)[0] == pytest.approx(1.0)
    # LOW demand with no interest → a trivial reply, minimal complexity.
    assert reply_delay_inputs(AnswerDemand.LOW, interest=0.0)[0] == pytest.approx(0.0)
    # MEDIUM demand (0.5) with mid interest (0.5) → the midpoint.
    assert reply_delay_inputs(AnswerDemand.MEDIUM, interest=0.5)[0] == pytest.approx(0.5)


def test_interest_out_of_range_is_clamped_into_the_unit_interval() -> None:
    # A caller may hand a slightly out-of-range interest; complexity stays in [0, 1].
    complexity, _urgency = reply_delay_inputs(AnswerDemand.HIGH, interest=5.0)
    assert complexity == pytest.approx(1.0)
    complexity_low, _ = reply_delay_inputs(AnswerDemand.LOW, interest=-5.0)
    assert complexity_low == pytest.approx(0.0)
