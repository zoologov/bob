# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LlmVolatilityJudge — the Tier-0 realisation of the volatility-judgment seam (BOB-057 .1).

Implements the :class:`~bob.domain.personality.volatility_judgment.VolatilityJudge`
port with one cheap local Tier-0 call: the pure prompt builder folds the
:class:`~bob.domain.personality.volatility_judgment.VolatilityContext` into the
request, the router runs it on the local model, and the pure parser maps the reply
to a :class:`~bob.domain.personality.volatility_judgment.VolatilityVerdict`.

A thin shell on purpose — all decision shaping is pure domain. It does NOT swallow
router/model failures: a model/router error PROPAGATES, so the caller in .2 drops
the verify pass decoratively with the safe default (= «не проверять») rather than
answering from a silent guess. (A garbled *reply*, by contrast, is not an error —
the parser conservatively returns ``needs_check=False`` for it.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.volatility_judgment import (
    VOLATILITY_JUDGE_SYSTEM_PROMPT,
    build_volatility_user_prompt,
    parse_volatility_verdict,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.domain.personality.volatility_judgment import (
        VolatilityContext,
        VolatilityVerdict,
    )

__all__ = ["LlmVolatilityJudge"]


class LlmVolatilityJudge:
    """Decide whether the answer hinges on a fresh volatile fact via one Tier-0 call."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        """Run the Tier-0 volatility judgment for ``ctx`` and parse it into a verdict.

        Builds the request from the pure prompt builder, runs it on the local tier,
        and parses the reply. A router/model error propagates (no silent default)
        for the caller's decorative safe-default in .2.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_volatility_verdict(raw)

    @staticmethod
    def _request(ctx: VolatilityContext) -> LLMRequest:
        """Build the Tier-0 volatility-judgment request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.VOLATILITY_JUDGE,
            messages=[
                {"role": "system", "content": VOLATILITY_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_volatility_user_prompt(ctx)},
            ],
        )
