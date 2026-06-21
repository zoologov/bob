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
    from bob.application.usecases.apply_reflection import ApplyReflection
    from bob.application.usecases.handle_message import PersonalityState
    from bob.domain.personality.taste import TasteEngine
    from bob.domain.ports import Clock, JsonValue

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


class TasteProfileWriter(Protocol):
    """The narrow persistence seam self-evolution needs: write a JSON artifact.

    A focused view of ``SoulStore`` (interface segregation) — the reflect tick
    only ever persists the evolved ``taste_profile``, so it depends on this one
    method rather than the full soul-store contract.
    """

    def write_json(self, name: str, data: JsonValue) -> None: ...


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
    """Periodic Tier 0 reflection: logged as an episode, then applied to the soul.

    After persisting the reflection as memory, an optional self-evolution step
    (``apply_reflection`` + ``soul_store``) lets the reflection reshape Bob's
    tastes (BOB-013 Фаза 2). It is **idempotent**: the same reflection text is
    applied at most once — ``last_evolved`` records the last applied reflection so
    a re-run of the identical tick is a no-op. Without the evolution collaborators
    wired the tick is log-only (its prior behaviour).
    """

    def __init__(
        self,
        *,
        router: LLMRouter,
        repo: EpisodeWriter,
        state: PersonalityState,
        clock: Clock,
        language: str = DEFAULT_LANGUAGE,
        apply_reflection: ApplyReflection | None = None,
        soul_store: TasteProfileWriter | None = None,
    ) -> None:
        self._router = router
        self._repo = repo
        self._state = state
        self._clock = clock
        self._language = language
        self._apply_reflection = apply_reflection
        self._soul_store = soul_store
        # Idempotency marker: the last reflection text already applied to the soul.
        self._last_evolved: str | None = None

    async def run(self) -> None:
        """Reflect on Tier 0, log it as an episode, then (optionally) evolve the soul."""
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
        self._evolve(reflection)

    def _evolve(self, reflection: str) -> None:
        """Apply ``reflection`` to the soul once, persisting taste on a real change."""
        if self._apply_reflection is None or self._soul_store is None:
            return
        if reflection == self._last_evolved:  # idempotency: already applied.
            return
        self._last_evolved = reflection
        outcome = self._apply_reflection.run(reflection, self._state.soul)
        if not outcome.changed:
            return
        self._state.soul = outcome.soul
        self._soul_store.write_json("taste_profile", _taste_profile(outcome.soul.taste))


def _taste_profile(taste: TasteEngine) -> dict[str, object]:
    """Serialise a taste engine into the persisted ``taste_profile`` JSON shape.

    Mirrors the structure Genesis writes and ``_load_soul`` reads back, so an
    evolved soul round-trips across a restart.
    """
    return {
        "axes": [
            {
                "name": axis.name,
                "value": axis.value,
                "conviction": axis.conviction,
                "experience_count": axis.experience_count,
            }
            for axis in taste.axes
        ]
    }


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
