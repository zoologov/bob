# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Fascination — Bob's current passion, immutable, ageing/decaying (BOB-020)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bob.personality.fascination import (
    DECAY_FLOOR,
    MAX_INTENSITY,
    MIN_INTENSITY,
    Fascination,
    _clamp,
)


def _at(hours: float = 0.0) -> datetime:
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC) + timedelta(hours=hours)


class TestFascinationConstruction:
    def test_holds_topic_intensity_and_creation_time(self) -> None:
        f = Fascination(topic="орбитальная механика", intensity=0.8, created_at=_at())
        assert f.topic == "орбитальная механика"
        assert f.intensity == 0.8
        assert f.created_at == _at()

    def test_rejects_intensity_above_max(self) -> None:
        with pytest.raises(ValueError, match="intensity"):
            Fascination(topic="x", intensity=MAX_INTENSITY + 0.1, created_at=_at())

    def test_rejects_intensity_below_min(self) -> None:
        with pytest.raises(ValueError, match="intensity"):
            Fascination(topic="x", intensity=MIN_INTENSITY - 0.1, created_at=_at())

    def test_rejects_blank_topic(self) -> None:
        with pytest.raises(ValueError, match="topic"):
            Fascination(topic="   ", intensity=0.5, created_at=_at())

    def test_is_immutable(self) -> None:
        f = Fascination(topic="x", intensity=0.5, created_at=_at())
        with pytest.raises(AttributeError):
            f.intensity = 0.9  # type: ignore[misc]


class TestAgeing:
    def test_intensity_wanes_with_age(self) -> None:
        fresh = Fascination(topic="x", intensity=1.0, created_at=_at())
        aged = fresh.aged(now=_at(hours=24))
        assert aged.intensity < fresh.intensity
        assert aged.topic == fresh.topic
        assert aged.created_at == fresh.created_at

    def test_decay_is_monotonic_over_time(self) -> None:
        fresh = Fascination(topic="x", intensity=1.0, created_at=_at())
        a = fresh.aged(now=_at(hours=12)).intensity
        b = fresh.aged(now=_at(hours=48)).intensity
        assert b < a

    def test_decay_is_bounded_below_at_min(self) -> None:
        fresh = Fascination(topic="x", intensity=1.0, created_at=_at())
        far = fresh.aged(now=_at(hours=10_000))
        assert far.intensity >= MIN_INTENSITY

    def test_no_negative_age_boost(self) -> None:
        # A 'now' before creation never inflates intensity above the stored value.
        fresh = Fascination(topic="x", intensity=0.6, created_at=_at(hours=10))
        assert fresh.aged(now=_at(hours=0)).intensity <= 0.6

    def test_age_at_creation_is_unchanged(self) -> None:
        fresh = Fascination(topic="x", intensity=0.7, created_at=_at())
        assert fresh.aged(now=_at()).intensity == pytest.approx(0.7)


class TestDecayFloor:
    def test_faded_is_true_once_aged_below_floor(self) -> None:
        fresh = Fascination(topic="x", intensity=1.0, created_at=_at())
        faded = fresh.aged(now=_at(hours=10_000))
        assert faded.intensity <= DECAY_FLOOR
        assert faded.has_faded()

    def test_fresh_strong_fascination_has_not_faded(self) -> None:
        fresh = Fascination(topic="x", intensity=0.9, created_at=_at())
        assert not fresh.aged(now=_at(hours=1)).has_faded()


class TestClampBoundary:
    """The defensive intensity clamp — the never-runaway guardrail invariant."""

    def test_clamp_keeps_a_valid_intensity_unchanged(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_clamp_pins_above_max_back_to_max(self) -> None:
        assert _clamp(MAX_INTENSITY + 1.0) == MAX_INTENSITY

    def test_clamp_pins_below_min_back_to_min(self) -> None:
        assert _clamp(MIN_INTENSITY - 1.0) == MIN_INTENSITY

    def test_clamp_maps_nan_to_min_never_propagates(self) -> None:
        # Defensive guard: a NaN intensity (degenerate arithmetic) must collapse to the
        # floor, never propagate — intensity stays a real, bounded scalar (no runaway).
        assert _clamp(float("nan")) == MIN_INTENSITY
