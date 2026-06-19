# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

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

This layer only orchestrates: every bound/clamp and the vector math live in the
domain, so the use-case stays thin and the rules stay testable without an LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.mood import Mood, MoodDelta

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.domain.ports import Clock

logger = logging.getLogger(__name__)

# How strongly each signal moves its mood axis per update.
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

    def __init__(self, *, router: LLMRouter, clock: Clock) -> None:
        self._router = router
        self._clock = clock

    async def run(self, mood: Mood, signals: TextSignals) -> Mood:
        """Return ``mood`` updated from ``signals`` (sentiment + frequency/time/presence)."""
        sentiment = await self._classify_sentiment(signals.text)
        delta = MoodDelta(
            valence=self._valence_step(sentiment),
            arousal=self._arousal_step(signals.message_count),
            social=self._social_step(present=signals.present),
        )
        return mood.update(delta)

    async def _classify_sentiment(self, text: str) -> str:
        """Run Tier 0 sentiment classification through the router."""
        request = LLMRequest(
            task_type=TaskType.SENTIMENT,
            messages=[
                {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        label = await self._router.run(request)
        return label.strip().casefold()

    @staticmethod
    def _valence_step(sentiment: str) -> float:
        if sentiment in _POSITIVE_LABELS:
            return _SENTIMENT_VALENCE_STEP
        if sentiment in _NEGATIVE_LABELS:
            return -_SENTIMENT_VALENCE_STEP
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
