# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ProactiveTick — the heartbeat wrapper over the ProactivityEngine.

The tick is a thin adapter: each ``run`` drives the engine once. These tests pin
that it delegates to the engine and surfaces the engine's spoke/silent outcome,
using a fake engine (no LLM, no gateway), so the periodic loop's scheduling stays
the runtime's concern and is covered there.
"""

from __future__ import annotations

from bob.application.proactivity.tick import ProactiveTick


class FakeEngine:
    """Records tick invocations and returns a scripted spoke outcome."""

    def __init__(self, *, spoke: bool) -> None:
        self._spoke = spoke
        self.ticks = 0

    async def tick(self) -> bool:
        self.ticks += 1
        return self._spoke


async def test_tick_runs_engine_once_when_silent() -> None:
    # Arrange
    engine = FakeEngine(spoke=False)
    tick = ProactiveTick(engine=engine)

    # Act
    await tick.run()

    # Assert: the engine was driven exactly once.
    assert engine.ticks == 1


async def test_tick_runs_engine_once_when_speaking() -> None:
    # Arrange
    engine = FakeEngine(spoke=True)
    tick = ProactiveTick(engine=engine)

    # Act
    await tick.run()

    # Assert
    assert engine.ticks == 1
