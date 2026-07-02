# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity-app

"""ProactiveTick — drive the ProactivityEngine on the heartbeat cadence.

The heartbeat sibling of the inner-monologue / reflect ticks
(:mod:`bob.application.usecases.heartbeat`): a one-shot coroutine the runtime
schedules via :func:`bob.application.runtime.heartbeat.periodic`. Each cycle it
runs the :class:`~bob.application.proactivity.engine.ProactivityEngine` once.
Because the engine's decision is pure and defaults to silence, the overwhelming
majority of ticks return immediately having made ZERO LLM calls — so running this
on the (~30s) heartbeat cadence stays cheap, with the LLM only firing on the rare
tick where Bob genuinely decides to speak.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class ProactiveRunner(Protocol):
    """The engine seam the tick drives: run one proactive decision, report if spoke."""

    async def tick(self) -> bool:
        """Run one proactive tick; return whether Bob spoke."""
        ...


class ProactiveTick:
    """A heartbeat tick that runs the proactivity engine once per cycle."""

    def __init__(self, *, engine: ProactiveRunner) -> None:
        self._engine = engine

    async def run(self) -> None:
        """Run one proactive tick; log when Bob actually spoke."""
        spoke = await self._engine.tick()
        if spoke:
            logger.info("proactive tick: Bob spoke")
