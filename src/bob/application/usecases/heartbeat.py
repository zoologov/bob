# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Heartbeat ticks — Bob's autonomous inner life between messages.

The parallel heartbeat of RFC §"Поток обработки": lightweight, periodic work the
runtime schedules as background tasks (see :class:`bob.application.runtime`).
Three ticks, each a thin orchestrator over the pure domain and the local Tier 0
path (privacy: inner life never escalates to the remote API):

* :class:`InnerMonologueTick` — Bob "thinks" privately on Tier 0; the thought's
  sentiment nudges his mood, so the inner monologue feeds Mood.
* :class:`MoodDriftTick` — emotional homeostasis: mood decays a step toward its
  resting baseline (:meth:`Mood.drift_toward`), so transient spikes fade.
* :class:`ReflectTick` — a periodic Tier 0 reflection, logged as an episode so the
  experience is remembered.

All three read/write the shared :class:`~bob.application.usecases.handle_message.PersonalityState`
so ticks and message handling see one consistent mood.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.memory.entities import EpisodicEvent
from bob.domain.personality.language import DEFAULT_LANGUAGE, language_directive
from bob.domain.personality.mood import MoodDelta

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router.llm_router import LLMRouter
    from bob.application.usecases.handle_message import PersonalityState
    from bob.domain.ports import Clock

logger = logging.getLogger(__name__)

# How sentiment of an inner thought nudges valence per tick.
_MONOLOGUE_VALENCE_STEP = 0.1

# Fraction of the gap to baseline that mood drifts back each tick.
_DRIFT_RATE = 0.1

_POSITIVE_LABELS = frozenset({"positive", "pos", "good"})
_NEGATIVE_LABELS = frozenset({"negative", "neg", "bad"})

_MONOLOGUE_PROMPT = (
    "In one short sentence, think a private thought as Bob right now, then on a "
    "new line classify its mood as exactly one lowercase word: positive, "
    "negative, or neutral."
)
_REFLECT_PROMPT = (
    "As Bob, write one short, reflective sentence about how things have been "
    "going lately. Keep it private and introspective."
)


def _localised(prompt: str, language: str) -> str:
    """Prepend the persona language directive to a self-generated prompt (BOB-012).

    Inner-monologue and reflection prompts have no user message to mirror, so they
    must carry an explicit language constraint or the model drifts to English.
    """
    return f"{language_directive(language)}\n{prompt}"


class EpisodeWriter(Protocol):
    """The persistence seam the reflect tick needs: save an episode."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...


class InnerMonologueTick:
    """Bob thinks privately on Tier 0; the thought's sentiment feeds his mood."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        state: PersonalityState,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._router = router
        self._state = state
        self._language = language

    async def run(self) -> None:
        """Generate a private thought, classify it, and nudge mood accordingly."""
        thought = await self._router.run(
            LLMRequest(
                task_type=TaskType.INNER_MONOLOGUE,
                messages=[
                    {
                        "role": "system",
                        "content": _localised(_MONOLOGUE_PROMPT, self._language),
                    }
                ],
            )
        )
        delta = MoodDelta(valence=_valence_step(_last_label(thought)))
        self._state.soul = self._state.soul.with_mood(self._state.soul.mood.update(delta))
        logger.debug("inner monologue tick applied valence delta %.3f", delta.valence)


class MoodDriftTick:
    """Pull the current mood a step back toward its resting baseline."""

    def __init__(self, *, state: PersonalityState) -> None:
        self._state = state

    async def run(self) -> None:
        """Drift mood toward baseline (emotional homeostasis between stimuli)."""
        soul = self._state.soul
        drifted = soul.mood.drift_toward(soul.mood_baseline, rate=_DRIFT_RATE)
        self._state.soul = soul.with_mood(drifted)


class ReflectTick:
    """Periodic Tier 0 reflection, persisted as an episodic memory."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        repo: EpisodeWriter,
        state: PersonalityState,
        clock: Clock,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._router = router
        self._repo = repo
        self._state = state
        self._clock = clock
        self._language = language

    async def run(self) -> None:
        """Reflect on Tier 0 and log the reflection as an episode."""
        reflection = await self._router.run(
            LLMRequest(
                task_type=TaskType.REFLECT,
                messages=[
                    {
                        "role": "system",
                        "content": _localised(_REFLECT_PROMPT, self._language),
                    }
                ],
            )
        )
        now = self._clock.now()
        episode = EpisodicEvent(
            ts=now,
            event_type="reflection",
            content=reflection,
            mood_snapshot=self._state.soul.mood.tone(),
            tags=("heartbeat",),
        )
        await self._repo.save_episode(_episode_row(episode))


def _episode_row(episode: EpisodicEvent) -> dict[str, object]:
    """Map an episodic entity to the repo's raw mapping form."""
    return {
        "ts": episode.ts.isoformat(),
        "event_type": episode.event_type,
        "content": episode.content,
        "mood_snapshot": episode.mood_snapshot,
        "tags": ",".join(episode.tags),
    }


def _last_label(thought: str) -> str:
    """Take the last non-empty line of an inner thought as its sentiment label."""
    lines = [line.strip().casefold() for line in thought.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _valence_step(label: str) -> float:
    if label in _POSITIVE_LABELS:
        return _MONOLOGUE_VALENCE_STEP
    if label in _NEGATIVE_LABELS:
        return -_MONOLOGUE_VALENCE_STEP
    return 0.0
