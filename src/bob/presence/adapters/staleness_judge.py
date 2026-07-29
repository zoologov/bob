# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=infrastructure

"""LlmStalenessJudge — the Tier-0 realisation of the staleness-judge seam (BOB-066 Срез W.3).

Implements the :class:`~bob.presence.ports.StalenessJudge` port with one cheap local Tier-0
call: the pure prompt builder folds the
:class:`~bob.presence.staleness.StalenessContext` (the draft + what landed during generation)
into the request, the router runs it on the local model, and the pure parser maps the reply to
a :class:`~bob.presence.staleness.StalenessReading`.

A thin shell on purpose — all decision shaping is pure domain. The parser is fail-safe (a
garbled reply reads as «ничего не сместилось» → the pure gate SENDs), and a router/model error
propagates so the врезка's decorative caller degrades to a plain SEND rather than dropping a
reply from a silent guess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.presence.staleness_judgment import (
    STALENESS_JUDGE_SYSTEM_PROMPT,
    build_staleness_user_prompt,
    parse_staleness_reading,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.presence.staleness import StalenessContext, StalenessReading

__all__ = ["LlmStalenessJudge"]


class LlmStalenessJudge:
    """Read how the context shifted under a drafted reply via one Tier-0 call."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def assess(self, ctx: StalenessContext) -> StalenessReading:
        """Run the Tier-0 staleness read for ``ctx`` and parse it into a reading.

        Builds the request from the pure prompt builder, runs it on the local tier, and parses
        the reply (fail-safe: a garbled read → all-False → the gate SENDs).
        """
        raw = await self._router.run(self._request(ctx))
        return parse_staleness_reading(raw)

    @staticmethod
    def _request(ctx: StalenessContext) -> LLMRequest:
        """Build the Tier-0 staleness-judge request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.STALENESS_JUDGE,
            messages=[
                {"role": "system", "content": STALENESS_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_staleness_user_prompt(ctx)},
            ],
        )
