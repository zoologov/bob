# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""UpdateMoodFromText — derive text signals into a mood update (GUPPI use-case).

The perceive step of perceive→decide→act (RFC §"Поток обработки"). It reads four
signals from an incoming message and turns them into a :class:`MoodDelta` that
the pure :class:`Mood` domain applies:

* **sentiment** — classified on the local **Tier 0** path of the
  :class:`LLMRouter` (privacy: personality-adjacent work stays local), nudging
  *valence*;
* **message frequency** — a burst is stimulating, lifting *arousal*;
* **time of day** — read from the injected :class:`Clock` (never
  ``datetime.now()``); late night winds *arousal* down;
* **presence** — an engaged user lifts *social*, absence lowers it.

On top of these, **social co-regulation** (BOB-033 .3) makes interaction genuinely
charge Bob back up: the sentiment→valence step is scaled by the *asymmetric*
disposition magnitudes (a warm message lifts more than a cold one dips —
:meth:`Disposition.positive_lift_scale` > :meth:`Disposition.negative_dip_scale`),
and a clearly warm message additionally pulls mood a proportional fraction toward
the disposition baseline (:meth:`Mood.lift_toward`, rate from
:meth:`Disposition.social_lift_rate`) so a warm exchange *displaces accumulated low*
rather than only adding a delta — the structural anti-depressant ("you cheer up
talking to people").

This layer only orchestrates: every bound/clamp and the vector math live in the
domain, so the use-case stays thin and the rules stay testable without an LLM.

🔴 The mood read is a SIDE step of the turn (BOB-116 D13). The sentiment goes through
:meth:`LLMRouter.run_optional`: when Tier 0 cannot serve it (a revoked key, an outage) the
whole update is skipped and the mood is returned exactly as it was — not reset to neutral,
and without the frequency/time/presence nudges either, so an outage leaves no trace in how
Bob feels. Until D13 that 403 propagated out of the turn before the voice door, and with
no understudy the room got silence instead of the honest GUPPI notice. A failure that is
not an outage (a contract defect, a database error) still propagates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.personality.disposition import DEFAULT_DISPOSITION
from bob.personality.mood import Mood, MoodDelta

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.kernel.ports import Clock
    from bob.personality.disposition import Disposition

logger = logging.getLogger(__name__)

# Base sentiment→valence step, then scaled by the disposition's asymmetric
# contagion magnitudes (positive lift > negative dip) in ``_valence_step``.
_SENTIMENT_VALENCE_STEP = 0.2
_FREQUENCY_AROUSAL_STEP = 0.2
_LATE_NIGHT_AROUSAL_STEP = 0.15
_PRESENCE_SOCIAL_STEP = 0.15

# A message run at or above this count counts as a stimulating burst.
_BURST_MESSAGE_COUNT = 3

# Hours (inclusive start, exclusive end) considered "late night" — winding down.
_LATE_NIGHT_START_HOUR = 0
_LATE_NIGHT_END_HOUR = 6

# Tier 0 sentiment labels mapped to a valence direction.
_POSITIVE_LABELS = frozenset({"positive", "pos", "good"})
_NEGATIVE_LABELS = frozenset({"negative", "neg", "bad"})

_SENTIMENT_SYSTEM_PROMPT = (
    "Classify the sentiment of the user's message as exactly one lowercase word: "
    "positive, negative, or neutral. Reply with only that word."
)


@dataclass(frozen=True, slots=True)
class TextSignals:
    """The raw per-message signals the use-case reads to update mood."""

    text: str
    message_count: int
    present: bool


class UpdateMoodFromText:
    """Turn incoming-text signals into a mood update via Tier 0 sentiment + Clock."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        clock: Clock,
        disposition: Disposition = DEFAULT_DISPOSITION,
    ) -> None:
        self._router = router
        self._clock = clock
        # Bob's stable temperament drives the asymmetric social contagion (BOB-033 .3):
        # the warm-vs-cold valence asymmetry and the proportional pull-toward-baseline.
        # Defaults to canon-Bob so an unwired construction behaves as a strong optimist.
        self._disposition = disposition

    async def run(
        self, mood: Mood, signals: TextSignals, *, target: Mood | None = None
    ) -> Mood:
        """Return ``mood`` updated from ``signals`` (sentiment + frequency/time/presence).

        ``target`` is the disposition baseline used for social co-regulation
        (BOB-033 .3): on a clearly POSITIVE incoming message it pulls mood a
        proportional fraction toward ``target`` (:meth:`Mood.lift_toward`),
        displacing accumulated low. ``None`` (the default) skips that pull, so the
        update is the (disposition-scaled) per-signal delta alone — backward-compatible.
        """
        sentiment = await self._classify_sentiment(signals.text)
        if sentiment is None:
            return mood  # Tier 0 could not serve the read: the step is skipped (BOB-116 D13)
        # "Displace the low" FIRST (BOB-033 .3): a warm message charges Bob back up
        # toward his baseline before the per-signal delta lands, so the warm exchange
        # genuinely lifts him out of a dip rather than only nudging valence.
        lifted = self._co_regulate(mood, sentiment, target)
        delta = MoodDelta(
            valence=self._valence_step(sentiment),
            arousal=self._arousal_step(signals.message_count),
            social=self._social_step(present=signals.present),
        )
        return lifted.update(delta)

    def _co_regulate(self, mood: Mood, sentiment: str, target: Mood | None) -> Mood:
        """Pull ``mood`` toward ``target`` on a warm message (the social-charge tug)."""
        if target is None or sentiment not in _POSITIVE_LABELS:
            return mood
        return mood.lift_toward(target, rate=self._disposition.social_lift_rate())

    async def _classify_sentiment(self, text: str) -> str | None:
        """Run Tier 0 sentiment classification; ``None`` when Tier 0 could not serve it."""
        request = LLMRequest(
            task_type=TaskType.SENTIMENT,
            messages=[
                {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        label = await self._router.run_optional(request)
        return None if label is None else label.strip().casefold()

    def _valence_step(self, sentiment: str) -> float:
        """Asymmetric sentiment→valence step: a warm message lifts more than a cold dips.

        Scaled by the disposition's contagion magnitudes (BOB-033 .3): the positive
        lift always exceeds the negative dip, so connection moves Bob up more than
        negativity drags him down — the structural anti-depressant.
        """
        if sentiment in _POSITIVE_LABELS:
            return _SENTIMENT_VALENCE_STEP * self._disposition.positive_lift_scale()
        if sentiment in _NEGATIVE_LABELS:
            return -_SENTIMENT_VALENCE_STEP * self._disposition.negative_dip_scale()
        return 0.0

    def _arousal_step(self, message_count: int) -> float:
        burst = _FREQUENCY_AROUSAL_STEP if message_count >= _BURST_MESSAGE_COUNT else 0.0
        late = -_LATE_NIGHT_AROUSAL_STEP if self._is_late_night() else 0.0
        return burst + late

    @staticmethod
    def _social_step(*, present: bool) -> float:
        return _PRESENCE_SOCIAL_STEP if present else -_PRESENCE_SOCIAL_STEP

    def _is_late_night(self) -> bool:
        hour = self._clock.now().hour
        return _LATE_NIGHT_START_HOUR <= hour < _LATE_NIGHT_END_HOUR
