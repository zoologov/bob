# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""ClassifyCodingIntent — cheap Tier-0 «coding vs chat» classifier (BOB-041 .2).

When the owner talks to Bob naturally in his topic, this decides whether the message
is a REQUEST FOR BOB TO DO DEV WORK ON HIS REPO (create/edit/fix code, files or tests)
versus ordinary conversation. It mirrors the sentiment classifier: one cheap Tier-0
call returning a single word, parsed CONSERVATIVELY — only an exact ``coding`` answer
counts, and any other word, garbage, or a flaky local model defaults to ``chat``
(``False``). Conservatism is a safety property: a false-positive only proposes a PLAN
behind the unbypassable gate (no edits), so the floor is "when in doubt, just chat".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter

logger = logging.getLogger(__name__)

__all__ = ["ClassifyCodingIntent"]

# The single label that counts as a dev-work request; anything else → chat.
_CODING_LABEL = "coding"

# Punctuation trimmed off the model's one-word answer before the exact-match check.
_LABEL_TRIM = " \t\n.!?,:;'\""

_CODING_INTENT_SYSTEM_PROMPT = (
    "Decide whether the user's message asks the assistant to do software-development "
    "work on its OWN code repository — create, edit or fix files/code/tests, implement "
    "a feature, write tests, refactor. Reply with exactly one lowercase word: 'coding' "
    "if it is such a dev-work request, or 'chat' for ordinary conversation. Reply with "
    "only that word."
)


class ClassifyCodingIntent:
    """Decide whether an owner message is a dev-work request, via a Tier-0 call."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def is_coding_request(self, text: str) -> bool:
        """Return whether ``text`` asks Bob to do dev work on his repo (conservative).

        Runs the cheap Tier-0 ``coding``/``chat`` classification; only an exact
        ``coding`` answer is treated as a request. A flaky model (or any non-``coding``
        word) defaults to ``False`` so a misread never opens a coding session.
        """
        try:
            label = await self._router.run(self._request(text))
        except Exception:
            logger.exception("coding-intent classification failed (defaulting to chat)")
            return False
        return label.strip(_LABEL_TRIM).casefold() == _CODING_LABEL

    @staticmethod
    def _request(text: str) -> LLMRequest:
        """Build the Tier-0 coding-intent classification request for ``text``."""
        return LLMRequest(
            task_type=TaskType.CODING_INTENT,
            messages=[
                {"role": "system", "content": _CODING_INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
