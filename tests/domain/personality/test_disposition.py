# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure :class:`Disposition` trait (BOB-033 .1).

A disposition is the stable temperament from which Bob's canon-optimism emerges:
high optimism makes him more likely to reappraise a dark thought, and it tilts
social contagion asymmetrically — a warm message lifts him more than a cold one
drags him down. These are pure derivations the later beads (.2 reappraisal,
.3 social-contagion) only read.
"""

from __future__ import annotations

import pytest

from bob.domain.personality.disposition import DEFAULT_DISPOSITION, Disposition


@pytest.mark.parametrize(
    ("optimism", "resilience"),
    [(-0.01, 0.5), (1.01, 0.5), (0.5, -0.01), (0.5, 1.01)],
)
def test_out_of_range_traits_raise(optimism: float, resilience: float) -> None:
    # Arrange / Act / Assert: traits are bounded to [0, 1], like a Mood axis.
    with pytest.raises(ValueError, match="must be within"):
        Disposition(optimism=optimism, resilience=resilience)


def test_bounds_are_inclusive() -> None:
    # The closed interval endpoints are valid.
    assert Disposition(optimism=0.0, resilience=0.0).optimism == 0.0
    assert Disposition(optimism=1.0, resilience=1.0).resilience == 1.0


def test_canonical_default_is_highly_optimistic() -> None:
    # Canon-Bob is an optimist by temperament, not by script.
    canon = Disposition.canonical()
    assert canon is DEFAULT_DISPOSITION
    assert canon.optimism >= 0.8


def test_reappraisal_probability_is_a_valid_probability() -> None:
    # The derivation must stay in [0, 1] across the trait range.
    for optimism in (0.0, 0.3, 0.8, 1.0):
        prob = Disposition(optimism=optimism, resilience=0.5).reappraisal_probability()
        assert 0.0 <= prob <= 1.0


def test_reappraisal_probability_is_monotonic_in_optimism() -> None:
    # More optimistic Bob reframes a dark thought more readily.
    low = Disposition(optimism=0.2, resilience=0.5).reappraisal_probability()
    mid = Disposition(optimism=0.5, resilience=0.5).reappraisal_probability()
    high = Disposition(optimism=0.9, resilience=0.5).reappraisal_probability()
    assert low < mid < high


def test_lift_and_dip_scales_are_non_negative_magnitudes() -> None:
    disp = Disposition(optimism=0.6, resilience=0.6)
    assert disp.positive_lift_scale() > 0.0
    assert disp.negative_dip_scale() > 0.0


def test_positive_lift_exceeds_negative_dip_across_trait_range() -> None:
    # The core asymmetry: connection lifts Bob more than negativity drags him —
    # the structural anti-depressant. Holds for every disposition.
    for optimism in (0.0, 0.25, 0.5, 0.75, 1.0):
        for resilience in (0.0, 0.5, 1.0):
            disp = Disposition(optimism=optimism, resilience=resilience)
            assert disp.positive_lift_scale() > disp.negative_dip_scale()


def test_positive_lift_is_monotonic_in_optimism() -> None:
    low = Disposition(optimism=0.2, resilience=0.5).positive_lift_scale()
    high = Disposition(optimism=0.9, resilience=0.5).positive_lift_scale()
    assert low < high


def test_negative_dip_shrinks_with_resilience() -> None:
    # A more resilient Bob is dragged down less by the same negative input.
    fragile = Disposition(optimism=0.5, resilience=0.1).negative_dip_scale()
    sturdy = Disposition(optimism=0.5, resilience=0.9).negative_dip_scale()
    assert sturdy < fragile


def test_disposition_is_frozen() -> None:
    disp = Disposition(optimism=0.5, resilience=0.5)
    with pytest.raises(AttributeError):
        disp.optimism = 0.9  # type: ignore[misc]  # frozen-dataclass guard under test
