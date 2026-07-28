# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`ReappraiseReflection` — the probabilistic reappraisal beat (BOB-033 .2).

After a reflection is generated, this use-case classifies its sentiment on Tier 0.
If it is NEGATIVE, with a probability drawn from the disposition (a seeded, injected
RNG → deterministic), it runs a SECOND beat on Tier 1 — "find the constructive good
in this thought, as Bob would" — and returns the reframed thought plus a positive
valence step. With probability ``1 - p`` the thought stays honestly sad (returned
as-is, no step). Positive/neutral thoughts are never reappraised. This is the human
"crowd out bad with good" — probabilistic, never mechanical.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from bob.application.router.llm_router import (
    _PREFERRED_TIER,
    _TIER_LOCAL,
    LLMRouter,
    TaskType,
)
from bob.personality.disposition import Disposition
from bob.personality.usecases.reappraise_reflection import (
    REAPPRAISAL_VALENCE_STEP,
    ReappraiseReflection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class RecordingProvider:
    """A provider that records its calls and returns a fixed reply per tier."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls.append(" ".join(m.get("content", "") for m in messages))
        return self.reply


def _routers(
    *, sentiment: str, reframed: str
) -> tuple[LLMRouter, RecordingProvider, RecordingProvider]:
    # Tier 0 serves the sentiment label (SENTIMENT task default); Tier 1 serves the
    # reappraised thought (the reappraisal beat is forced to Tier 1).
    tier0 = RecordingProvider(reply=sentiment)
    tier1 = RecordingProvider(reply=reframed)
    return LLMRouter(providers={0: tier0, 1: tier1}), tier0, tier1


# A disposition whose reappraisal_probability() is well inside (0, 1): optimism 0.5 ->
# 0.2 + 0.7*0.5 = 0.55, so a draw < 0.55 fires and a draw >= 0.55 does not.
_DISPOSITION = Disposition(optimism=0.5, resilience=0.7)


class _FixedRng(random.Random):
    """A Random whose ``random()`` always returns a fixed draw (deterministic gating)."""

    def __init__(self, draw: float) -> None:
        super().__init__()
        self._draw = draw

    def random(self) -> float:
        return self._draw


async def test_negative_thought_under_p_is_reappraised_on_tier1() -> None:
    router, _tier0, tier1 = _routers(
        sentiment="negative", reframed="но телескоп почти готов"
    )
    reappraise = ReappraiseReflection(
        router=router, rng=_FixedRng(0.1), disposition=_DISPOSITION
    )

    outcome = await reappraise.run("всё впустую и тихо")

    assert outcome.reappraised is True
    assert outcome.thought == "но телескоп почти готов"
    assert outcome.valence_step == REAPPRAISAL_VALENCE_STEP
    assert tier1.calls, "the reappraisal beat must run on Tier 1"


async def test_negative_thought_over_p_stays_sad() -> None:
    router, _tier0, tier1 = _routers(sentiment="negative", reframed="unused")
    reappraise = ReappraiseReflection(
        router=router, rng=_FixedRng(0.9), disposition=_DISPOSITION
    )

    outcome = await reappraise.run("всё впустую и тихо")

    assert outcome.reappraised is False
    assert outcome.thought == "всё впустую и тихо"  # stays honestly sad, unchanged
    assert outcome.valence_step == 0.0
    assert tier1.calls == []  # no Tier-1 beat when the draw is over p


async def test_positive_thought_is_never_reappraised() -> None:
    router, _tier0, tier1 = _routers(sentiment="positive", reframed="unused")
    # Even with a draw that WOULD fire on a negative thought, a positive one is left be.
    reappraise = ReappraiseReflection(
        router=router, rng=_FixedRng(0.0), disposition=_DISPOSITION
    )

    outcome = await reappraise.run("сегодня собрал телескоп, славно")

    assert outcome.reappraised is False
    assert outcome.thought == "сегодня собрал телескоп, славно"
    assert outcome.valence_step == 0.0
    assert tier1.calls == []


async def test_neutral_thought_is_never_reappraised() -> None:
    router, _tier0, tier1 = _routers(sentiment="neutral", reframed="unused")
    reappraise = ReappraiseReflection(
        router=router, rng=_FixedRng(0.0), disposition=_DISPOSITION
    )

    outcome = await reappraise.run("проверил крепление линзы")

    assert outcome.reappraised is False
    assert outcome.valence_step == 0.0
    assert tier1.calls == []


async def test_sentiment_is_classified_on_tier0() -> None:
    router, tier0, _tier1 = _routers(sentiment="neutral", reframed="unused")
    reappraise = ReappraiseReflection(
        router=router, rng=_FixedRng(0.0), disposition=_DISPOSITION
    )

    await reappraise.run("проверил крепление линзы")

    # Sentiment classification stays local (Tier 0) — privacy: only the reappraisal
    # beat escalates to Tier 1.
    assert tier0.calls, "sentiment must be classified on Tier 0"


async def test_seeded_rng_makes_the_decision_reproducible() -> None:
    # Two runs with the same seed make the identical gating decision.
    outcomes = []
    for _ in range(2):
        router, _t0, _t1 = _routers(sentiment="negative", reframed="reframed")
        reappraise = ReappraiseReflection(
            router=router,
            rng=random.Random(7),  # noqa: S311
            disposition=_DISPOSITION,
        )
        outcomes.append((await reappraise.run("всё впустую")).reappraised)
    assert outcomes[0] == outcomes[1]


def test_reflect_task_default_keeps_sentiment_on_tier0() -> None:
    # Guard: the SENTIMENT task must remain a Tier-0 default so classification is local.
    assert _PREFERRED_TIER[TaskType.SENTIMENT] == _TIER_LOCAL
