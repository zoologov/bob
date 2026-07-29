# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""DelayedTurn (BOB-066 Срез 2.3) — the human floor under how fast Bob's reply lands.

The application coordinator that gives Bob a *living* reply cadence (INV-9). It wraps
the real reply generation and guarantees the reply never lands faster than the human
floor computed by the pure
:class:`~bob.presence.natural_delay.NaturalDelayPolicy`: it waits
``max(natural_floor, real_generation_time)``. Because real generation counts toward
the floor, this NEVER makes Bob slower than he really is — it only stops him being
inhumanly instant on a trivial reply. The floor is derived from the drafted reply's
length + complexity, relieved by urgency (a demanded, time-critical answer comes
quicker — urgency is fed from the existing ``classify_answer_demand`` + topic
interest by the caller).

The clock (``monotonic``) and the wait (``sleep``) are injected, so the coordinator
is deterministic and unit-testable with fakes — no real time passes in a test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bob.presence.natural_delay import NaturalDelayPolicy


class DelayedTurn:
    """Ensures a generated reply never lands faster than its human floor."""

    def __init__(
        self,
        policy: NaturalDelayPolicy,
        *,
        sleep: Callable[[float], Awaitable[None]],
        monotonic: Callable[[], float],
    ) -> None:
        self._policy = policy
        self._sleep = sleep
        self._monotonic = monotonic

    async def deliver(
        self,
        generate: Callable[[], Awaitable[str]],
        *,
        complexity: float,
        urgency: float,
    ) -> str:
        """Run ``generate`` and top the elapsed time up to the human floor.

        The floor is computed from the *generated* reply's length (so it reflects
        what Bob actually said) plus ``complexity``, relieved by ``urgency``. If real
        generation already took at least that long, the reply lands immediately;
        otherwise the coordinator sleeps only the remaining gap.
        """
        start = self._monotonic()
        reply = await generate()
        elapsed = self._monotonic() - start

        floor = self._policy.floor_seconds(
            char_len=len(reply), complexity=complexity, urgency=urgency
        )
        remaining = floor - elapsed
        if remaining > 0.0:
            await self._sleep(remaining)
        return reply
