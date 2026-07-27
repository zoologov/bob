# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the should_speak decision — urge → probability → seeded sample + veto."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from bob.domain.personality.mood import Mood
from bob.proactivity.decision import ProactiveDecider, urge_to_probability
from bob.proactivity.governance import Governance, ProactiveHistory

# A clear waking-hours "now" and an unconstrained history (governance allows).
_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
_CLEAR = ProactiveHistory(
    last_spoke_at=None, last_user_msg_at=None, sent_in_window=0, muted=False
)


class _FixedClock:
    """A Clock stub returning a fixed instant — no datetime.now() in the domain."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def test_urge_to_probability_is_monotonic() -> None:
    # Act / Assert: a higher urge never maps to a lower probability.
    assert urge_to_probability(0.1) < urge_to_probability(0.5) < urge_to_probability(0.9)


def test_urge_to_probability_is_bounded() -> None:
    # Act / Assert: a logistic map stays strictly within (0, 1).
    for urge in (0.0, 0.25, 0.5, 0.75, 1.0):
        prob = urge_to_probability(urge)
        assert 0.0 < prob < 1.0


def test_should_speak_high_urge_fires_under_seed() -> None:
    # Arrange: a high urge and a seed; the same draw is reproducible.
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())
    mood = Mood(arousal=1.0, openness=1.0, social=1.0)

    # Act
    fired = decider.should_speak(
        mood=mood,
        silence_seconds=200_000.0,
        salience=1.0,
        social_energy=1.0,
        history=_CLEAR,
        rng=random.Random(0),
    )

    # Assert: a strong drive in a clear window does fire.
    assert fired is True


def test_should_speak_is_deterministic_under_fixed_seed() -> None:
    # Arrange: two independent RNGs seeded identically.
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())
    mood = Mood(arousal=0.3, openness=0.3, social=0.3)

    def run(seed: int) -> bool:
        return decider.should_speak(
            mood=mood,
            silence_seconds=5000.0,
            salience=0.4,
            social_energy=0.6,
            history=_CLEAR,
            rng=random.Random(seed),
        )

    # Act / Assert: identical seeds → identical decisions.
    assert run(42) == run(42)


def test_should_speak_respects_governance_veto() -> None:
    # Arrange: a maximal urge, but the owner muted proactivity.
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())
    muted = ProactiveHistory(
        last_spoke_at=None, last_user_msg_at=None, sent_in_window=0, muted=True
    )

    # Act
    fired = decider.should_speak(
        mood=Mood(arousal=1.0, openness=1.0, social=1.0),
        silence_seconds=1_000_000.0,
        salience=1.0,
        social_energy=1.0,
        history=muted,
        rng=random.Random(0),
    )

    # Assert: governance overrides any urge.
    assert fired is False


def test_should_speak_quiet_hours_veto() -> None:
    # Arrange: maximal urge but it is 03:00 local (quiet hours).
    night = _NOW.replace(hour=3)
    decider = ProactiveDecider(clock=_FixedClock(night), governance=Governance())

    # Act
    fired = decider.should_speak(
        mood=Mood(arousal=1.0, openness=1.0, social=1.0),
        silence_seconds=1_000_000.0,
        salience=1.0,
        social_energy=1.0,
        history=_CLEAR,
        rng=random.Random(0),
    )

    # Assert
    assert fired is False


def test_should_speak_uses_injected_clock_for_time_of_day() -> None:
    # Arrange: the decider reads the hour from the Clock, not datetime.now().
    morning = _NOW.replace(hour=9)
    decider = ProactiveDecider(clock=_FixedClock(morning), governance=Governance())

    # Act: a borderline urge — sampling many seeds yields a stable fire rate.
    fires = sum(
        decider.should_speak(
            mood=Mood(),
            silence_seconds=3600.0,
            salience=0.2,
            social_energy=0.5,
            history=_CLEAR,
            rng=random.Random(seed),
        )
        for seed in range(200)
    )

    # Assert: some fire, some don't — it is a genuine stochastic sample.
    assert 0 < fires < 200


def test_low_urge_rarely_fires_over_many_seeds() -> None:
    # Arrange: a minimal drive in a clear window.
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())

    # Act
    fires = sum(
        decider.should_speak(
            mood=Mood(arousal=-1.0, openness=-1.0, social=-1.0),
            silence_seconds=0.0,
            salience=0.0,
            social_energy=0.0,
            history=_CLEAR,
            rng=random.Random(seed),
        )
        for seed in range(200)
    )
    high_fires = sum(
        decider.should_speak(
            mood=Mood(arousal=1.0, openness=1.0, social=1.0),
            silence_seconds=1_000_000.0,
            salience=1.0,
            social_energy=1.0,
            history=_CLEAR,
            rng=random.Random(seed),
        )
        for seed in range(200)
    )

    # Assert: low drive fires far less often than high drive.
    assert fires < high_fires


def test_decider_does_not_mutate_history() -> None:
    # Arrange
    decider = ProactiveDecider(clock=_FixedClock(_NOW), governance=Governance())
    history = ProactiveHistory(
        last_spoke_at=_NOW - timedelta(hours=2),
        last_user_msg_at=None,
        sent_in_window=1,
        muted=False,
    )

    # Act
    decider.should_speak(
        mood=Mood(),
        silence_seconds=1000.0,
        salience=0.2,
        social_energy=0.5,
        history=history,
        rng=random.Random(1),
    )

    # Assert: the history value object is untouched.
    assert history.sent_in_window == 1
