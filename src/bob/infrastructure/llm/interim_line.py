# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LlmInterimLineGenerator — the Tier-0 live interim line (BOB-057 .3, US-3b).

Realises the interim-line seam with one cheap local Tier-0 call: the pure prompt
builder folds ``topic`` + ``sender_name`` into the request, the router runs it on
the local model, and the pure cleaner reduces the reply to a single addressed
one-liner in Bob's voice («Леш, гляну свежие ставки, секунду 🙂»).

A thin shell on purpose — all shaping is pure domain
(:mod:`bob.domain.personality.interim_line`). It does NOT swallow router/model
failures: an error PROPAGATES so the caller (the progress announcer) falls back to
a seeded BOB-055 phrase, keeping the whole interim decorative in one place. The
+1-2s of a local gen is fine — the turn is about to wait on the web search anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.interim_line import (
    INTERIM_LINE_SYSTEM_PROMPT,
    build_interim_line_user_prompt,
    clean_interim_line,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter

__all__ = ["LlmInterimLineGenerator"]


class LlmInterimLineGenerator:
    """Generate one live, addressed interim one-liner via a Tier-0 call."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def generate(self, *, topic: str, sender_name: str) -> str:
        """Run the Tier-0 interim-line gen for ``topic``/``sender_name`` and clean it.

        Builds the request from the pure prompt builder, runs it on the local tier,
        and reduces the reply to one tidy line. A router/model error propagates (no
        silent default) for the announcer's seeded fallback.
        """
        raw = await self._router.run(self._request(topic=topic, sender_name=sender_name))
        return clean_interim_line(raw)

    @staticmethod
    def _request(*, topic: str, sender_name: str) -> LLMRequest:
        """Build the Tier-0 interim-line request for ``topic``/``sender_name``."""
        return LLMRequest(
            task_type=TaskType.INTERIM_LINE,
            messages=[
                {"role": "system", "content": INTERIM_LINE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_interim_line_user_prompt(
                        topic=topic, sender_name=sender_name
                    ),
                },
            ],
        )
