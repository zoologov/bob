# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for DelayedTurn — the human floor coordinator (INV-9, deterministic)."""

from __future__ import annotations

from bob.application.runtime.delayed_turn import DelayedTurn
from bob.presence.natural_delay import NaturalDelayPolicy


class _FakeClock:
    """A manually-advanced monotonic clock; ``sleep`` advances it (no real wait)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def _delayed_turn(clock: _FakeClock, *, gen_seconds: float = 0.0) -> DelayedTurn:
    return DelayedTurn(
        NaturalDelayPolicy(), sleep=clock.sleep, monotonic=clock.monotonic
    )


async def test_instant_generation_is_topped_up_to_the_floor() -> None:
    # Arrange: generation returns immediately (no time advanced during generate).
    clock = _FakeClock()
    turn = _delayed_turn(clock)

    async def generate() -> str:
        return "ок"

    # Act
    reply = await turn.deliver(generate, complexity=0.0, urgency=0.0)

    # Assert: the reply is correct AND the coordinator slept a human floor.
    assert reply == "ок"
    assert clock.slept
    assert clock.slept[0] > 1.0


async def test_slow_generation_wins_no_extra_sleep() -> None:
    # Arrange: generation itself takes longer than the floor.
    clock = _FakeClock()
    turn = _delayed_turn(clock)

    async def generate() -> str:
        clock.t += 100.0  # generation "took" 100s (well past any floor)
        return "долгий разбор"

    # Act
    await turn.deliver(generate, complexity=0.0, urgency=0.0)

    # Assert: real generation already exceeded the floor ⇒ no top-up sleep.
    assert clock.slept == []


async def test_urgent_reply_sleeps_less_than_a_calm_one() -> None:
    # Arrange: identical instant generation, differing urgency.
    calm_clock = _FakeClock()
    urgent_clock = _FakeClock()

    async def generate() -> str:
        return "вот подробный ответ на твой вопрос"

    # Act
    await _delayed_turn(calm_clock).deliver(generate, complexity=0.3, urgency=0.0)
    await _delayed_turn(urgent_clock).deliver(generate, complexity=0.3, urgency=1.0)

    # Assert: urgency relieves the floor ⇒ a shorter top-up.
    assert urgent_clock.slept[0] < calm_clock.slept[0]


async def test_returns_exactly_the_generated_reply() -> None:
    # Arrange
    clock = _FakeClock()
    turn = _delayed_turn(clock)

    async def generate() -> str:
        return "точный текст"

    # Act
    reply = await turn.deliver(generate, complexity=0.5, urgency=0.2)

    # Assert
    assert reply == "точный текст"
