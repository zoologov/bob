# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

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
from bob.conversation.conversation import RepeatThresholds, is_bob_repeat
from bob.memory.entities import EpisodicEvent
from bob.personality.language import DEFAULT_LANGUAGE, language_directive
from bob.personality.mood import MoodDelta
from bob.personality.reflection import (
    build_monologue_prompt,
    build_reflection_prompt,
    select_reflection_angle,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from random import Random

    from bob.application.router.llm_router import LLMRouter
    from bob.application.usecases.handle_message import PersonalityState
    from bob.kernel.ports import Clock, JsonValue
    from bob.personality.taste import TasteEngine
    from bob.personality.usecases.apply_reflection import ApplyReflection
    from bob.personality.usecases.reappraise_reflection import ReappraisalOutcome

logger = logging.getLogger(__name__)

# How sentiment of an inner thought nudges valence per tick.
_MONOLOGUE_VALENCE_STEP = 0.1

# Fraction of the gap to baseline that mood drifts back each tick.
_DRIFT_RATE = 0.1

# Homeostatic band (BOB-030): a private thought may colour valence only within
# ``baseline ± _MONOLOGUE_VALENCE_BAND``. Conditioning the monologue on the current
# mood (BOB-029) created a positive-feedback loop — a bright thought lifts valence,
# which makes the next thought brighter — that walked valence to the ±1 rail
# (observed at 1.0). Bounding Bob's OWN ruminations to a band around his resting
# baseline keeps him emotionally stable (orbiting the baseline, no ceiling/floor
# swings); real external events may still move mood further and then decay via drift.
_MONOLOGUE_VALENCE_BAND = 0.4


def _bounded_valence_delta(*, current: float, baseline: float, step: float) -> float:
    """Clamp a self-generated valence nudge to the homeostatic band (BOB-030).

    The monologue may move valence toward the thought's sentiment, but never past
    ``baseline ± _MONOLOGUE_VALENCE_BAND`` in the away-from-baseline direction, so
    Bob's own thoughts cannot spiral his mood to an extreme. If valence is already
    beyond the band (from a strong external event) the thought neither pushes it
    further out nor yanks it back — homeostatic drift handles the return.
    """
    raw = current + step
    if step > 0:
        ceiling = max(baseline + _MONOLOGUE_VALENCE_BAND, current)
        return min(raw, ceiling) - current
    if step < 0:
        floor = min(baseline - _MONOLOGUE_VALENCE_BAND, current)
        return max(raw, floor) - current
    return 0.0


_POSITIVE_LABELS = frozenset({"positive", "pos", "good"})
_NEGATIVE_LABELS = frozenset({"negative", "neg", "bad"})

# How many of Bob's most-recent episodes the reflect tick reads to GROUND a fresh
# reflection in what is happening now (a handful — enough flavour, not the whole log).
_DEFAULT_REFLECT_GROUNDING = 3
# How many recent REFLECTION episodes the reflect tick compares a fresh thought
# against for near-duplicate detection (the anti-record window).
_DEFAULT_REFLECT_DEDUP_WINDOW = 5
# The dedup window counts REFLECTIONS, but the episode log interleaves message turns.
# Fetch this many times the dedup window of raw episodes so the scan still finds the
# intended number of reflections even amid a burst of messages (the tick is slow, so a
# larger read costs nothing). Grounding still takes only the freshest tail, unaffected.
_DEDUP_FETCH_FACTOR = 6


def _localised(prompt: str, language: str) -> str:
    """Prepend the persona language directive to a self-generated prompt (BOB-012).

    Inner-monologue and reflection prompts have no user message to mirror, so they
    must carry an explicit language constraint or the model drifts to English.
    """
    return f"{language_directive(language)}\n{prompt}"


class EpisodeWriter(Protocol):
    """The persistence seam the reflect tick needs: save an episode."""

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...


class ReflectionContext(Protocol):
    """The narrow READ seam that grounds + de-duplicates reflections (BOB-026 .2).

    Realised structurally by :class:`~bob.memory.adapters.sqlite_memory_repo.SqliteMemoryRepo`
    (which already exposes ``recent_episodes``). It serves Bob's most-recent episodes
    (oldest-first) so the reflect tick can (1) GROUND a fresh reflection in what is
    happening now instead of a static template, and (2) compare the fresh thought
    against recent REFLECTION episodes to suppress near-duplicates (the stuck record).
    Optional: unwired, the reflect tick uses the legacy generic prompt and saves every
    reflection — exactly its prior behaviour.
    """

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        """Return the last ``k`` episodes by recency, oldest-first."""
        ...


class Reappraiser(Protocol):
    """The narrow seam the reflect tick drives to reappraise a dark thought (BOB-033 .2).

    Realised by :class:`~bob.personality.usecases.reappraise_reflection.ReappraiseReflection`:
    after a reflection is generated it classifies the thought's sentiment (Tier 0) and,
    only for a NEGATIVE one, with a seeded-RNG probability drawn from Bob's disposition,
    runs a Tier-1 beat that reframes it constructively and returns a positive valence
    step. Otherwise the thought is returned as-is with a zero step (the honest low).
    Driven BEFORE the reflection is logged, so the (possibly reframed) text is what is
    stored. Optional: unwired, the reflect tick behaves exactly as before.
    """

    async def run(self, reflection: str) -> ReappraisalOutcome:
        """Maybe reframe ``reflection``; return the (possibly new) thought + mood step."""
        ...


class FascinationEvolver(Protocol):
    """The narrow seam the reflect tick drives to evolve Bob's fascination (BOB-020).

    Realised by :class:`~bob.personality.usecases.evolve_fascination.EvolveFascination`:
    a rare, grounded, idempotent step that — only when the current passion has spent
    itself — picks a fresh one from Bob's real inner life. Driven AFTER the reflection
    is logged so that fresh reflection is available as grounding. Optional: unwired,
    the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Run one fascination-evolution step (a no-op unless a shift is due)."""
        ...


class PhantomEvolver(Protocol):
    """The narrow seam the reflect tick drives to evolve Bob's phantom prefs (BOB-020).

    Realised by :class:`~bob.personality.usecases.evolve_phantoms.EvolvePhantoms`: a
    rare, grounded, slow, idempotent step that lets Bob's phantom preferences shift
    over time — a fresh symphony emerges from a real strong taste/reflection, an old
    one fades. Driven AFTER the reflection is logged so that fresh reflection is
    available as grounding. Optional: unwired, the reflect tick behaves as before.
    """

    async def run(self) -> None:
        """Run one phantom-evolution step (a no-op unless a shift is due)."""
        ...


class MemoryConsolidator(Protocol):
    """The narrow seam the reflect tick drives to consolidate old memory (BOB-021).

    Realised by :class:`~bob.memory.usecases.consolidate_memory.ConsolidateMemory`:
    a rare, non-destructive, idempotent step that folds OLD un-consolidated episodes
    into a Tier-0 digest (embedded, recalled like any episode) and flags the sources.
    Driven AFTER the reflection is logged, on the same slow cadence. Optional: unwired,
    the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Run one consolidation step (a no-op unless an eligible batch is due)."""
        ...


class FactDeduper(Protocol):
    """The narrow seam the reflect tick drives to merge near-duplicate facts (BOB-021).

    Realised by :class:`~bob.memory.usecases.dedup_facts.DedupFacts`: a rare,
    conservative, non-destructive, idempotent step that merges near-duplicate semantic
    facts (cosine of embeddings above a conservative threshold) into a canonical one,
    flagging the rest superseded — so Bob's facts stay clean without false merges.
    Driven AFTER the reflection is logged, on the same slow cadence. Optional: unwired,
    the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Run one dedup step (a no-op unless near-duplicate facts are due)."""
        ...


class SulkRecoverer(Protocol):
    """The narrow seam the reflect tick drives to recover Bob's обида (BOB-014 .2b).

    Realised by :class:`~bob.social.usecases.sulk_sources.SulkRecoveryStep`: a
    step that decays обида by the REAL elapsed time since the last tick — the GUARANTEED
    exit, since time alone always brings Bob back (no permanent lock-out). Driven on the
    same slow cadence as the other reflect-tick steps. Idempotent and a no-op when Bob
    is not hurt. Optional: unwired, the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Run one обида-recovery step (a no-op unless Bob is currently hurt)."""
        ...


class PatternDetectorStep(Protocol):
    """The narrow seam the reflect tick drives to detect self-patterns (BOB-028 .2).

    Realised by :class:`~bob.proactivity.usecases.detect_patterns.DetectPatterns`: a
    rare, metacognitive step that gathers signals about Bob's own behaviour (self-
    repeats, addressivity outcomes, verbosity misses, relationship deltas, a stuck
    mood, owner friction, what landed), asks a detector to formulate human-readable
    candidate rules, de-duplicates them against existing ones, and PERSISTS new
    candidates in ``PROPOSED`` — it only PROPOSES, never applies (application is .3).
    Driven AFTER the reflection is logged, on the same slow cadence. Optional: unwired,
    the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Run one pattern-detection step (a no-op unless fresh candidates are due)."""
        ...


class RuleAnnouncerStep(Protocol):
    """The narrow seam the reflect tick drives to voice a proposed rule (BOB-028 .3).

    Realised by
    :class:`~bob.proactivity.usecases.announce_rules.AnnounceProposedRules`: a rare,
    tactful step where Bob speaks ONE fresh ``PROPOSED`` self-improvement rule to the
    owner IN HIS OWN WORDS (:mod:`bob.proactivity.rule_voice`, BOB-096 срез 5) and marks
    it announced so he does not repeat it. Driven AFTER pattern detection on the same
    slow cadence (a freshly proposed rule can be voiced next tick). It only PROPOSES —
    owner approval (the apply gate) happens via the ``/rule approve`` command, never
    here. Best-effort and
    optional: unwired, the reflect tick behaves exactly as before.
    """

    async def run(self) -> None:
        """Voice one un-announced proposed rule (a no-op unless one is pending)."""
        ...


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
        """Generate a private thought, classify it, and nudge mood accordingly.

        The prompt is conditioned on Bob's CURRENT mood (BOB-029): a generic
        "think a private thought" prompt let the Tier-0 model default to gloom,
        whose negative sentiment dragged valence down and trapped him in a minor
        key. Mirroring the live mood makes a bright mood yield a bright thought,
        so the monologue reinforces the baseline instead of fighting it.
        """
        prompt = build_monologue_prompt(self._state.soul.mood.tone())
        thought = await self._router.run(
            LLMRequest(
                task_type=TaskType.INNER_MONOLOGUE,
                messages=[
                    {
                        "role": "system",
                        "content": _localised(prompt, self._language),
                    }
                ],
            )
        )
        mood = self._state.soul.mood
        step = _valence_step(_last_label(thought))
        delta = MoodDelta(
            valence=_bounded_valence_delta(
                current=mood.valence,
                baseline=self._state.soul.mood_baseline.valence,
                step=step,
            )
        )
        self._state.soul = self._state.soul.with_mood(mood.update(delta))
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
        evolve_fascination: FascinationEvolver | None = None,
        evolve_phantoms: PhantomEvolver | None = None,
        consolidate_memory: MemoryConsolidator | None = None,
        dedup_facts: FactDeduper | None = None,
        recover_sulk: SulkRecoverer | None = None,
        detect_patterns: PatternDetectorStep | None = None,
        announce_rules: RuleAnnouncerStep | None = None,
        reappraise: Reappraiser | None = None,
        reflection_context: ReflectionContext | None = None,
        rng: Random | None = None,
        repeat_thresholds: RepeatThresholds | None = None,
        grounding_episodes: int = _DEFAULT_REFLECT_GROUNDING,
        dedup_window: int = _DEFAULT_REFLECT_DEDUP_WINDOW,
    ) -> None:
        self._router = router
        self._repo = repo
        self._state = state
        self._clock = clock
        self._language = language
        self._apply_reflection = apply_reflection
        self._soul_store = soul_store
        # The grounding + dedup read seam (BOB-026 .2): serves recent episodes so a
        # fresh reflection is grounded in NOW and checked against recent reflections
        # for near-duplicates. Unwired -> the legacy generic prompt, every reflection
        # saved (prior behaviour).
        self._reflection_context = reflection_context
        # The seeded-RNG seam for reflection-angle rotation (BOB-047 .1): an injected,
        # seeded Random (the same style as the BOB-033 reappraisal gate) makes the
        # per-tick angle deterministic in tests yet varied tick to tick. Unwired (or with
        # no context seam) the tick adds no angle directive — legacy behaviour.
        self._rng = rng
        # Near-duplicate thresholds — reuse the .1 reply predicate's bar (verbatim OR
        # near-verbatim via difflib). Injected from config; conservative defaults.
        self._repeat_thresholds = (
            repeat_thresholds if repeat_thresholds is not None else RepeatThresholds()
        )
        # How many recent episodes ground the prompt, and how many recent reflection
        # episodes the dedup compares against.
        self._grounding_episodes = grounding_episodes
        self._dedup_window = dedup_window
        # The fascination-evolution seam (BOB-020 wave 2): driven AFTER the reflection
        # is logged (so it is available as grounding). Itself idempotent — it shifts
        # only when the current passion has faded — so a re-run in the same period is a
        # no-op. Unwired, the tick behaves exactly as before.
        self._evolve_fascination = evolve_fascination
        # The phantom-evolution seam (BOB-020 wave 3): same cadence — driven AFTER the
        # reflection is logged (so it is available as grounding). Itself slow and
        # idempotent (a grounded candidate already present is a no-op), so a re-run in
        # the same period causes no churn. Unwired, the tick behaves as before.
        self._evolve_phantoms = evolve_phantoms
        # The memory-consolidation seam (BOB-021): same slow cadence — driven AFTER the
        # reflection is logged. Itself rare, idempotent and non-destructive (only OLD
        # un-consolidated episodes are folded into a digest; a re-run with nothing
        # eligible is a no-op), so a re-run in the same period causes no churn. Unwired,
        # the tick behaves exactly as before.
        self._consolidate_memory = consolidate_memory
        # The fact-dedup seam (BOB-021): same slow cadence — driven AFTER the reflection
        # is logged. Itself rare, conservative, idempotent and non-destructive (only
        # near-duplicate facts above a high cosine threshold are merged; a re-run with
        # nothing to merge is a no-op), so a re-run in the same period causes no churn.
        # Unwired, the tick behaves exactly as before.
        self._dedup_facts = dedup_facts
        # The обида-recovery seam (BOB-014 .2b): same slow cadence — driven AFTER the
        # reflection is logged. It decays обида by the REAL elapsed time since the last
        # tick (the GUARANTEED exit — time alone brings Bob back, no permanent lock-out)
        # and is a no-op when Bob is not hurt. Unwired, the tick behaves as before.
        self._recover_sulk = recover_sulk
        # The pattern-detection seam (BOB-028 .2): same slow cadence — driven AFTER the
        # reflection is logged. It gathers signals about Bob's own behaviour, asks a
        # detector for candidate rules, de-duplicates them, and PERSISTS new ones in
        # PROPOSED — it only proposes, never applies (application is .3). Itself rare and
        # best-effort. Unwired, the tick behaves exactly as before.
        self._detect_patterns = detect_patterns
        # The rule-announce seam (BOB-028 .3): same slow cadence — driven AFTER pattern
        # detection so a freshly proposed rule can be voiced. Bob tactfully proposes ONE
        # un-announced PROPOSED rule to the owner; it only proposes (owner approval is the
        # /rule approve command), best-effort. Unwired, the tick behaves exactly as before.
        self._announce_rules = announce_rules
        # The probabilistic reappraisal seam (BOB-033 .2): driven BEFORE the reflection
        # is logged. For a NEGATIVE thought it may (with a disposition-/RNG-gated chance)
        # reframe it on Tier 1 and yield a positive valence step; otherwise the thought
        # stays honestly sad and mood is untouched. The lift is clamped to the BOB-030
        # homeostatic band, so reappraisal cannot spiral mood up. Unwired -> unchanged.
        self._reappraise = reappraise
        # Idempotency marker: the last reflection text already applied to the soul.
        self._last_evolved: str | None = None

    async def run(self) -> None:
        """Reflect on Tier 0, log it as an episode, then (optionally) evolve the soul.

        Grounds the reflection in fresh context (recent episodes + mood) when the
        read seam is wired (BOB-026 .2), then suppresses near-duplicates: a fresh
        thought that echoes a recent reflection is regenerated once (reusing the .1
        :func:`is_bob_repeat` predicate); if the retry still echoes one, the
        reflection is skipped — so the inner monologue stops being a stuck record.
        """
        recent = await self._recent_episodes()
        reflection = await self._reflect(recent)
        recent_reflections = _reflection_contents(recent, self._dedup_window)
        if self._is_near_duplicate(reflection, recent_reflections):
            reflection = await self._reflect(recent)
            if self._is_near_duplicate(reflection, recent_reflections):
                logger.debug("reflect tick skipped a near-duplicate reflection")
                return
        reflection = await self._reappraised(reflection)
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
        if self._evolve_fascination is not None:
            await self._evolve_fascination.run()
        if self._evolve_phantoms is not None:
            await self._evolve_phantoms.run()
        if self._consolidate_memory is not None:
            await self._consolidate_memory.run()
        if self._dedup_facts is not None:
            await self._dedup_facts.run()
        if self._recover_sulk is not None:
            await self._recover_sulk.run()
        if self._detect_patterns is not None:
            await self._detect_patterns.run()
        if self._announce_rules is not None:
            await self._announce_rules.run()

    async def _recent_episodes(self) -> Sequence[Mapping[str, object]]:
        """Read recent episodes for grounding + dedup (empty when no seam is wired).

        Over-fetches for dedup (``_DEDUP_FETCH_FACTOR x dedup_window``) so a burst of
        interleaved message turns cannot shrink the effective reflection window below
        ``dedup_window``. Grounding takes only the freshest tail, so the larger read
        does not change what grounds the reflection.
        """
        if self._reflection_context is None:
            return []
        want = max(self._grounding_episodes, self._dedup_window * _DEDUP_FETCH_FACTOR)
        return await self._reflection_context.recent_episodes(want)

    async def _reflect(self, recent: Sequence[Mapping[str, object]]) -> str:
        """Generate one reflection, grounded in ``recent`` when context is wired.

        With no context seam wired (``recent`` empty) the mood tone is withheld too,
        so :func:`build_reflection_prompt` returns the legacy generic prompt and the
        unwired tick is byte-for-byte unchanged.
        """
        grounding = _grounding_contents(recent, self._grounding_episodes)
        # Only ground (and lean) when the context seam is wired, so an unwired tick is
        # byte-for-byte unchanged. The disposition adds the few-shot living palette and
        # the optimism valence-lean (BOB-033 .2) on top of the existing NOW-grounding.
        mood_tone = self._state.soul.mood.tone() if self._reflection_context else ""
        disposition = self._state.soul.disposition if self._reflection_context else None
        # Rotate the inner-thought ANGLE per tick (BOB-047 .1) from the seeded RNG, but
        # only when both the RNG and the context seam are wired — so an unwired tick is
        # unchanged. The angle nudges the KIND of thought; mood-honesty is preserved.
        angle = (
            select_reflection_angle(self._rng)
            if self._rng is not None and self._reflection_context is not None
            else None
        )
        prompt = build_reflection_prompt(
            grounding, mood_tone=mood_tone, disposition=disposition, angle=angle
        )
        return await self._router.run(
            LLMRequest(
                task_type=TaskType.REFLECT,
                messages=[
                    {
                        "role": "system",
                        "content": _localised(prompt, self._language),
                    }
                ],
            )
        )

    async def _reappraised(self, reflection: str) -> str:
        """Maybe reframe a dark ``reflection`` and lift mood (BOB-033 .2).

        Drives the optional reappraisal seam: a NEGATIVE thought is, with a
        disposition-/RNG-gated chance, reframed constructively on Tier 1 and the
        returned positive step lifts mood (clamped to the BOB-030 homeostatic band, so
        no runaway). A positive/neutral thought, or a negative one that does not fire,
        is left honestly as-is with mood untouched. Unwired, returns the thought as-is.
        """
        if self._reappraise is None:
            return reflection
        outcome = await self._reappraise.run(reflection)
        if not outcome.reappraised:
            return reflection
        mood = self._state.soul.mood
        delta = MoodDelta(
            valence=_bounded_valence_delta(
                current=mood.valence,
                baseline=self._state.soul.mood_baseline.valence,
                step=outcome.valence_step,
            )
        )
        self._state.soul = self._state.soul.with_mood(mood.update(delta))
        return outcome.thought

    def _is_near_duplicate(self, reflection: str, recent_reflections: Sequence[str]) -> bool:
        """Whether ``reflection`` (near-)repeats a recent reflection (BOB-026 .2)."""
        return is_bob_repeat(
            reflection,
            recent_reflections,
            threshold=self._repeat_thresholds.similarity_threshold,
        )

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


def _grounding_contents(episodes: Sequence[Mapping[str, object]], limit: int) -> tuple[str, ...]:
    """The ``content`` of the ``limit`` most-recent NON-reflection episodes (BOB-047 .1).

    Grounds a reflection in what is actually happening now — REAL moments (messages,
    events, actions), NOT Bob's own prior reflections. Feeding past reflections back in
    as the few-shot "recent moments" made the model mimic its OWN register, locking the
    inner monologue into one tone (the mirror of the old stuck-gloom). Excluding
    ``event_type == "reflection"`` breaks that self-feeding loop; the dedup window
    (:func:`_reflection_contents`) STILL reads reflections, so BOB-026 is unaffected.
    ``episodes`` arrive oldest-first; the tail of length ``limit`` is the freshest.
    """
    if limit <= 0:
        return ()
    grounding = [
        str(row.get("content", "")) for row in episodes if row.get("event_type") != "reflection"
    ]
    return tuple(grounding[-limit:])


def _reflection_contents(episodes: Sequence[Mapping[str, object]], window: int) -> tuple[str, ...]:
    """The ``content`` of the recent REFLECTION episodes within ``window`` (BOB-026 .2).

    Dedup compares a fresh thought only against Bob's own recent REFLECTIONS, never
    message turns — so a reflection that merely echoes something the owner said is
    still kept. Filters to ``event_type == "reflection"``, newest-last, capped at
    ``window``.
    """
    if window <= 0:
        return ()
    reflections = [
        str(row.get("content", "")) for row in episodes if row.get("event_type") == "reflection"
    ]
    return tuple(reflections[-window:])


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
