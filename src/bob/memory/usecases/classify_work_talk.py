# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=application

"""ClassifyWorkTalk — cheap Tier-0 «this turn is about dev work?» classifier (BOB-087.C2).

The register-recall counterpart of :class:`~bob.coding.usecases.classify_coding_intent.
ClassifyCodingIntent`. Where that decides whether a message ASKS Bob to DO dev work, this
decides whether a turn is ABOUT Bob's dev work — «как продвигается разработка?», «что
построил?» — in ANY chat. A positive verdict lifts the turn into the DEV register so Bob's
``work`` recollections carry full recall weight (the owner's «direct question surfaces
work» mechanism). One cheap Tier-0 call returning a single word, parsed CONSERVATIVELY by
:func:`parse_work_talk_verdict`: only an exact ``work`` answer counts; any other word,
garbage, or a flaky local model defaults to ``chat`` (``False``). Conservatism is the safe
floor — a false negative merely keeps casual recall muting work (the default), never voices
private dev context the wrong way.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter

logger = logging.getLogger(__name__)

__all__ = ["ClassifyWorkTalk", "parse_work_talk_verdict"]

# The single label that marks a turn as being about dev work; anything else → chat.
_WORK_LABEL = "work"

# Punctuation trimmed off the model's one-word answer before the exact-match check.
_LABEL_TRIM = " \t\n.!?,:;'\""

_WORK_TALK_SYSTEM_PROMPT = (
    "Decide whether the user's message is ABOUT the assistant's software-development "
    "work — asking how its coding/development is going, what it built, coded, fixed or "
    "shipped, or the state of its repo/project. Reply with exactly one lowercase word: "
    "'work' if the message is about such dev work, or 'chat' for ordinary conversation. "
    "Reply with only that word."
)


def parse_work_talk_verdict(label: str) -> bool:
    """Whether ``label`` is the exact ``work`` verdict — pure and conservative.

    Trims surrounding punctuation/whitespace and case-folds, then requires an EXACT
    ``work`` match. Any other word, an empty/blank answer, or a multi-word reply is
    ``False`` (chat). Deterministic: same input → same verdict.
    """
    return label.strip(_LABEL_TRIM).casefold() == _WORK_LABEL


class ClassifyWorkTalk:
    """Decide whether a turn is about Bob's dev work, via a Tier-0 call."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def is_work_talk(self, text: str) -> bool:
        """Return whether ``text`` is about Bob's dev work (conservative).

        Runs the cheap Tier-0 ``work``/``chat`` classification; only an exact ``work``
        answer counts. A flaky model (or any non-``work`` word) defaults to ``False`` so
        a misread never spuriously lifts casual recall into the DEV register.
        """
        try:
            label = await self._router.run(self._request(text))
        except Exception:
            logger.exception("work-talk classification failed (defaulting to chat)")
            return False
        return parse_work_talk_verdict(label)

    @staticmethod
    def _request(text: str) -> LLMRequest:
        """Build the Tier-0 work-talk classification request for ``text``."""
        return LLMRequest(
            task_type=TaskType.WORK_TALK,
            messages=[
                {"role": "system", "content": _WORK_TALK_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
