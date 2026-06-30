# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LlmResponseJudge — the Tier-0 realisation of the response-judgment seam (BOB-049).

Implements the :class:`~bob.domain.personality.response_choice.ResponseJudge` port
with one cheap local Tier-0 call: the pure prompt builder folds the
:class:`~bob.domain.personality.response_choice.ResponseContext` into the request,
the router runs it on the local model, and the pure parser maps the reply to a
:class:`~bob.domain.personality.response_choice.ResponseChoice`.

A thin shell on purpose — all decision shaping is pure domain. It does NOT swallow
failures: a parse failure (:class:`ResponseJudgeParseError`) or a model/router
error PROPAGATES, so the fault-tolerant "full Bob or honest GUPPI notice" path
(BOB-049 .3) catches a real failure rather than Bob answering from a silent
default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.response_judgment import (
    RESPONSE_JUDGE_SYSTEM_PROMPT,
    build_judgment_user_prompt,
    parse_response_choice,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.domain.personality.response_choice import (
        ResponseChoice,
        ResponseContext,
    )

__all__ = ["LlmResponseJudge"]


class LlmResponseJudge:
    """Decide the response intent via one Tier-0 router call (raises on failure)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def decide(self, ctx: ResponseContext) -> ResponseChoice:
        """Run the Tier-0 judgment for ``ctx`` and parse it into a choice.

        Builds the request from the pure prompt builder, runs it on the local
        tier, and parses the reply. Any router/model error or an unparseable reply
        propagates (no silent default) for .3's retry/GUPPI-notice path.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_response_choice(raw)

    @staticmethod
    def _request(ctx: ResponseContext) -> LLMRequest:
        """Build the Tier-0 response-judgment request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.RESPONSE_JUDGE,
            messages=[
                {"role": "system", "content": RESPONSE_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_judgment_user_prompt(ctx)},
            ],
        )
