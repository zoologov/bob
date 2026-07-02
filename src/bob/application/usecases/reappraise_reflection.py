# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""ReappraiseReflection — the probabilistic reappraisal beat (BOB-033 .2).

Bob's human "crowd out bad with good": after a reflection is generated, this thin
use-case may reframe a DARK thought into a constructive one — but never mechanically.

1. **Classify** the reflection's sentiment on **Tier 0** (privacy: classification
   stays local, reusing the same one-word label the mood path uses).
2. If it is **negative**, draw the gate from an INJECTED seeded RNG against
   :meth:`Disposition.reappraisal_probability` — so a strong optimist reframes more
   readily, a weaker one less, and the decision is deterministic in tests.
3. On a fire, run a SECOND beat on **Tier 1** — "find the constructive good in this
   thought, as Bob would" — and return the reframed thought plus a positive valence
   step (the caller applies it through the BOB-030 homeostatic bound, so no runaway).
   On a miss the thought stays honestly sad: returned as-is, no step, no Tier-1 call.

Positive/neutral thoughts are never reappraised. Lows are allowed and NOT always
reframed — the anti-mechanistic shape the feature requires. Tier 1 is touched ONLY
for the reappraisal beat (the documented privacy compromise).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.language import DEFAULT_LANGUAGE, language_directive

if TYPE_CHECKING:
    from random import Random

    from bob.application.router.llm_router import LLMRouter
    from bob.domain.personality.disposition import Disposition

# Tier 0 sentiment labels marking a thought as negative (reuses the mood-path bar).
_NEGATIVE_LABELS = frozenset({"negative", "neg", "bad"})

# The Tier-1 destination for the reappraisal beat (its ONLY escalation off Tier 0).
_TIER_API = 1

# The positive valence step a successful reappraisal yields. The caller clamps it to
# the BOB-030 homeostatic band, so even a run of reappraisals cannot spiral mood up.
REAPPRAISAL_VALENCE_STEP = 0.1

_SENTIMENT_SYSTEM_PROMPT = (
    "Classify the sentiment of this private thought as exactly one lowercase word: "
    "positive, negative, or neutral. Reply with only that word."
)
_REAPPRAISAL_SYSTEM_PROMPT = (
    "Here is a private, somewhat dark thought of yours. As Bob — honestly, not with "
    "forced cheer — find the constructive or genuinely good side of it and rewrite it "
    "as one short, truthful sentence. Keep what is real; do not deny the difficulty."
)


@dataclass(frozen=True, slots=True)
class ReappraisalOutcome:
    """The result of a reappraisal attempt.

    ``reappraised`` is True only when a negative thought actually fired the Tier-1
    beat; then ``thought`` is the reframed text and ``valence_step`` is positive.
    Otherwise ``thought`` is the original and ``valence_step`` is ``0.0``.
    """

    thought: str
    valence_step: float
    reappraised: bool


def _localised(prompt: str, language: str) -> str:
    """Prepend the persona language directive to a self-generated prompt (BOB-012)."""
    return f"{language_directive(language)}\n{prompt}"


class ReappraiseReflection:
    """Probabilistically reframe a dark reflection into a constructive one (BOB-033 .2)."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        rng: Random,
        disposition: Disposition,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._router = router
        # A seeded, injected RNG: the reappraisal gate is deterministic in tests and
        # holds no global state (no direct ``random`` use).
        self._rng = rng
        self._disposition = disposition
        self._language = language

    async def run(self, reflection: str) -> ReappraisalOutcome:
        """Maybe reframe ``reflection``; return the (possibly new) thought + mood step.

        A no-op (returns the original, no step) for a positive/neutral thought, or a
        negative one whose seeded draw falls at/above the disposition's reappraisal
        probability — the honest low that is left to stand. Only on a fire is Tier 1
        touched and a positive valence step returned.
        """
        if not await self._is_negative(reflection):
            return ReappraisalOutcome(thought=reflection, valence_step=0.0, reappraised=False)
        if self._rng.random() >= self._disposition.reappraisal_probability():
            # The honest low: kept as-is, mood unchanged, no Tier-1 escalation.
            return ReappraisalOutcome(thought=reflection, valence_step=0.0, reappraised=False)
        reframed = await self._reframe(reflection)
        return ReappraisalOutcome(
            thought=reframed,
            valence_step=REAPPRAISAL_VALENCE_STEP,
            reappraised=True,
        )

    async def _is_negative(self, reflection: str) -> bool:
        """Classify the reflection's sentiment on Tier 0 (privacy: stays local)."""
        label = await self._router.run(
            LLMRequest(
                task_type=TaskType.SENTIMENT,
                messages=[
                    {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": reflection},
                ],
            )
        )
        return label.strip().casefold() in _NEGATIVE_LABELS

    async def _reframe(self, reflection: str) -> str:
        """Run the Tier-1 reappraisal beat — the ONLY escalation off Tier 0."""
        system = _localised(_REAPPRAISAL_SYSTEM_PROMPT, self._language)
        return await self._router.run(
            LLMRequest(
                task_type=TaskType.REFLECT,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": reflection},
                ],
                tier_override=_TIER_API,
            )
        )
