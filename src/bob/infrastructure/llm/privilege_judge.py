# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LlmPrivilegeJudge — the Tier-0 realisation of the privilege-judgment seam (BOB-052 .1).

Implements the :class:`~bob.domain.permission.privilege.PrivilegeJudge` port with one
cheap local Tier-0 call: the pure prompt builder folds the
:class:`~bob.domain.permission.privilege.PrivilegeContext` into the request, the router
runs it on the local model, and the pure parser maps the reply to a
:class:`~bob.domain.permission.privilege.PrivilegeNeed`.

A thin shell on purpose — all decision shaping is pure domain. It does NOT swallow
failures: a parse failure (:class:`PrivilegeJudgeParseError`) or a model/router error
PROPAGATES, so the caller in .3 drops the add-on decoratively with the safe default
(= refuse) rather than granting a privilege from a silent default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.permission.privilege import (
    PRIVILEGE_JUDGE_SYSTEM_PROMPT,
    build_privilege_user_prompt,
    parse_privilege_need,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.domain.permission.privilege import PrivilegeContext, PrivilegeNeed

__all__ = ["LlmPrivilegeJudge"]


class LlmPrivilegeJudge:
    """Decide whether a request needs owner permission via one Tier-0 call (raises on failure)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        """Run the Tier-0 privilege judgment for ``ctx`` and parse it into a need.

        Builds the request from the pure prompt builder, runs it on the local tier,
        and parses the reply. Any router/model error or an unparseable reply
        propagates (no silent default) for .3's decorative fault-tolerance.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_privilege_need(raw)

    @staticmethod
    def _request(ctx: PrivilegeContext) -> LLMRequest:
        """Build the Tier-0 privilege-judgment request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.PRIVILEGE_JUDGE,
            messages=[
                {"role": "system", "content": PRIVILEGE_JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": build_privilege_user_prompt(ctx)},
            ],
        )
