# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=infrastructure

"""LlmReactionJudge — the Tier-0 realisation of the reaction-judgment seam (BOB-050).

Implements the :class:`~bob.personality.reaction_meaning.ReactionJudge` port
with one cheap local Tier-0 call: the pure prompt builder folds the
:class:`~bob.personality.reaction_meaning.ReactionContext` into the request,
the router runs it on the local model, and the pure parser maps the reply to a
:class:`~bob.personality.reaction_meaning.ReactionMeaning`.

A thin shell on purpose — all meaning shaping is pure domain. It does NOT swallow
failures: a parse failure (:class:`ReactionJudgeParseError`) or a model/router error
PROPAGATES. The perceiving use-case is DECORATIVE, so it catches the failure and drops
the reaction silently rather than acting on a guessed meaning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.personality.reaction_judgment import (
    REACTION_JUDGE_SYSTEM_PROMPT,
    build_reaction_user_prompt,
    parse_reaction_meaning,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.personality.reaction_meaning import (
        ReactionContext,
        ReactionMeaning,
    )

__all__ = ["LlmReactionJudge"]


class LlmReactionJudge:
    """Interpret a reaction via one Tier-0 router call (raises on failure)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def interpret(self, ctx: ReactionContext) -> ReactionMeaning:
        """Run the Tier-0 judgment for ``ctx`` and parse it into a meaning.

        Builds the request from the pure prompt builder, runs it on the local tier,
        and parses the reply. Any router/model error or an unparseable reply
        propagates (no silent default) — the decorative perceiving path drops it.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_reaction_meaning(raw)

    @staticmethod
    def _request(ctx: ReactionContext) -> LLMRequest:
        """Build the Tier-0 reaction-judgment request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.REACTION_JUDGE,
            messages=[
                {"role": "system", "content": REACTION_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_reaction_user_prompt(ctx)},
            ],
        )
