# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""EngagementModel — Bob's appetite to converse + how short he answers (BOB-014/024).

The turn's «how much Bob wants to talk + how short he answers» concern in one cohesive
collaborator (extracted from ``HandleMessage`` in BOB-062.6b, wave 2, behavior-preserving).
It maps mood x topic interest x conversational fatigue x relationship to an
:class:`~bob.personality.expression.EngagementLevel`, runs the after-turn feedback loops (a
good interesting exchange lifts mood, an aimless turn tires Bob), and decides the BOB-024
:class:`~bob.personality.expression.Verbosity` (+ the optional length guard).

It lives in ``conversation`` (the «how the turn is conducted» vertical: brevity / engagement)
and imports its result value-objects back from ``personality`` — the legal one-way
conversation -> personality edge (pinned by ``tests/conversation/test_layering.py``).

🔴 The mutable per-boot holders (:class:`PersonalityState` mood, :class:`EngagementState`
fatigue) are passed IN per call (never captured), so the collaborator always reads/writes
``HandleMessage``'s CURRENT holders — the mood lift + fatigue decay accrue across turns
exactly as before. 🔴 It shares the SAME injected ``Random`` as every other turn
collaborator, so the per-turn draw order (plan -> **engagement** -> **verbosity** ->
addressivity -> surface/ack) is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.conversation.brevity import AnswerDemand, clamp_reply, decide_verbosity
from bob.conversation.engagement import (
    appetite_of,
    decide_engagement,
    engagement_mood_lift,
    topic_interest,
)
from bob.personality.mood import MoodDelta

if TYPE_CHECKING:
    from random import Random

    from bob.conversation.brevity import BrevityThresholds
    from bob.conversation.engagement import EngagementState, EngagementThresholds, FatigueRates
    from bob.kernel.ports import Clock
    from bob.personality.expression import EngagementLevel, ExpressionPlan, Verbosity
    from bob.personality.ports import CurrentFascinationReader
    from bob.personality.soul import SOUL
    from bob.personality.state import PersonalityState
    from bob.social.relationship import Relationship

logger = logging.getLogger(__name__)


class EngagementModel:
    """Decide Bob's appetite + reply length for one turn (BOB-014 .2a / BOB-024)."""

    def __init__(
        self,
        *,
        engagement_thresholds: EngagementThresholds,
        fatigue_rates: FatigueRates,
        engagement_mood_lift: float,
        fascination: CurrentFascinationReader | None,
        brevity_thresholds: BrevityThresholds,
        length_guard_enabled: bool,
        length_guard_max_chars: int,
        clock: Clock,
        rng: Random,
    ) -> None:
        self._engagement_thresholds = engagement_thresholds
        self._fatigue_rates = fatigue_rates
        self._engagement_mood_lift = engagement_mood_lift
        self._fascination = fascination
        self._brevity_thresholds = brevity_thresholds
        self._length_guard_enabled = length_guard_enabled
        self._length_guard_max_chars = length_guard_max_chars
        self._clock = clock
        self._rng = rng

    async def topic_interest(self, soul: SOUL, text: str) -> float:
        """Return how INTERESTING the inbound topic is to Bob, a [0, 1] scalar (BOB-014).

        Derived from his deterministic taste verdict + conviction on ``text`` (a strong
        love/hate is engaging, a NEUTRAL/unknown topic is "какие-попало" — low) and
        lifted when the topic MATCHES his current, non-faded fascination (the strongest
        pull — it clears the bar even on a bad day). The fascination match reuses the
        wired :class:`CurrentFascinationReader`; with no reader / no current passion the
        match is simply ``False``, so the interest is taste-only (behaviour as before).
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        match = await self._fascination_matches(text)
        return topic_interest(verdict, conviction, fascination_match=match)

    async def _fascination_matches(self, text: str) -> bool:
        """Whether the inbound topic is the thing Bob is currently fascinated by (BOB-014).

        Loads Bob's current, non-faded passion off the wired reader and checks whether
        its topic is mentioned in ``text`` (a light, case-insensitive substring match).
        No reader / no current fascination → ``False`` (a clean no-op). Best-effort —
        the appetite decision must never break on a flaky read, so a failure reads as no
        match rather than raising.
        """
        if self._fascination is None:
            return False
        try:
            fascination = await self._fascination.current_fascination()
        except Exception:
            logger.exception("reading current fascination for engagement failed (ignored)")
            return False
        if fascination is None:
            return False
        return fascination.topic.strip().casefold() in text.casefold()

    def decide_engagement(
        self,
        soul: SOUL,
        interest: float,
        relationship: Relationship | None,
        engagement_state: EngagementState,
        *,
        rng: Random | None = None,
    ) -> EngagementLevel:
        """Decide Bob's appetite LEVEL for this turn, decaying fatigue first (BOB-014 .2a).

        Decays the per-boot fatigue holder by the REAL elapsed time since the last turn
        (so appetite recovers between turns — the recovery guarantee), stores the decayed
        value back, then maps mood x ``interest`` x fatigue x ``relationship`` to an
        :class:`~bob.personality.expression.EngagementLevel` via the pure
        :func:`~bob.conversation.engagement.decide_engagement` (seeded by the same
        injected RNG, so the whole turn stays reproducible). The SHARED per-boot
        ``engagement_state`` holder is passed in (never captured).
        """
        now = self._clock.now()
        if engagement_state.last_turn_at is not None:
            elapsed = max(0.0, (now - engagement_state.last_turn_at).total_seconds())
            engagement_state.fatigue = engagement_state.fatigue.decayed(
                elapsed_seconds=elapsed, rates=self._fatigue_rates
            )
        return decide_engagement(
            mood=soul.mood,
            topic_interest=interest,
            fatigue=engagement_state.fatigue,
            relationship=relationship,
            # 🔴 BOB-066 Срез 2.1: the caller threads the turn-local ``TurnScope.rng`` so
            # concurrent chats never share a draw stream (INV-4); omitted → the injected rng.
            rng=rng if rng is not None else self._rng,
            thresholds=self._engagement_thresholds,
        )

    def reengage_for_room(
        self,
        soul: SOUL,
        interest: float,
        relationship: Relationship | None,
        engagement_state: EngagementState,
        *,
        threshold_shift: float,
        rng: Random | None = None,
    ) -> EngagementLevel:
        """Re-map the appetite level with a room-mood ``threshold_shift`` (BOB-066 Срез W.2).

        The room-mood analogue of :meth:`decide_engagement`, called on the reflective
        periphery-reply path ONLY (a warm room lifts Bob's appetite, a heavy/tense one
        dampens it — the shift comes BY VALUE from
        :func:`~bob.personality.room_tone.room_engagement_bias`). It re-runs the pure
        :func:`~bob.conversation.engagement.decide_engagement` over the ALREADY-decayed
        ``engagement_state.fatigue`` — it does NOT decay again (the base decision already
        did, this turn), so fatigue is never double-decayed. One extra seeded draw resolves
        the PLAYFUL boundary; it is taken only on this room-mood path (the base OFF path is
        untouched — byte-identical).
        """
        return decide_engagement(
            mood=soul.mood,
            topic_interest=interest,
            fatigue=engagement_state.fatigue,
            relationship=relationship,
            threshold_shift=threshold_shift,
            rng=rng if rng is not None else self._rng,
            thresholds=self._engagement_thresholds,
        )

    def apply_feedback(
        self,
        soul: SOUL,
        level: EngagementLevel,
        interest: float,
        state: PersonalityState,
        engagement_state: EngagementState,
    ) -> SOUL:
        """Run the after-turn engagement feedback loops (BOB-014 .2a) and stamp the clock.

        Two loops close the appetite model: (1) an interesting, well-engaged exchange
        (FULL/PLAYFUL on an interesting topic) lifts Bob's mood valence a touch — a small
        bounded :class:`~bob.personality.mood.MoodDelta` returned on a fresh soul
        snapshot, stored on the SHARED :class:`PersonalityState`; (2) the fatigue holder is
        updated with the turn outcome — an aimless turn tires Bob, an interesting one eases
        him — and ``last_turn_at`` is stamped so the next turn decays the elapsed gap.
        Returns the (possibly mood-lifted) soul so the caller persists the post-feedback
        mood. The SHARED per-boot holders are passed in (never captured).
        (Fascination grounding toward a well-going topic stays with the reflect-tick
        evolution path that already owns it — this loop only lifts mood + eases fatigue.)
        """
        interesting = interest >= self._engagement_thresholds.interesting
        lift = engagement_mood_lift(
            level, interesting=interesting, lift=self._engagement_mood_lift
        )
        if lift > 0.0:
            soul = soul.with_mood(soul.mood.update(MoodDelta(valence=lift)))
            state.soul = soul
        engagement_state.fatigue = engagement_state.fatigue.after_turn(
            interesting=interesting, rates=self._fatigue_rates
        )
        engagement_state.last_turn_at = self._clock.now()
        return soul

    def decide_verbosity(
        self,
        soul: SOUL,
        demand: AnswerDemand,
        interest: float,
        engagement: EngagementLevel,
        plan: ExpressionPlan,
        *,
        is_owner: bool,
        rng: Random | None = None,
    ) -> Verbosity:
        """Decide how SHORT Bob answers this turn — pure, deterministic by seed (BOB-024).

        Folds the already-computed turn signals into the pure
        :func:`~bob.conversation.brevity.decide_verbosity`: the message's
        answer-``demand`` is the base; topic ``interest`` can rarely upgrade it (seeded);
        a low ``mood_valence`` / thin appetite (the :class:`EngagementLevel` mapped to a
        [0, 1] appetite via :func:`~bob.conversation.engagement.appetite_of`) pull
        it down; the BOB-018 ``form_hint`` is a mood length lean (now an INPUT, not a
        rival directive); and a HIGH-demand owner is never clipped below NORMAL. The
        seeded ``roll`` is one draw off the same injected RNG, so the whole turn stays
        reproducible. ``is_owner`` (turn-local, passed in) keys off the perceived
        interlocutor (BOB-019) — resolved by the caller so this vertical need not read the
        social identity type.
        """
        # 🔴 BOB-066 Срез 2.1: turn-local ``TurnScope.rng`` (INV-4); omitted → injected rng.
        roll = (rng if rng is not None else self._rng).random()
        return decide_verbosity(
            demand=demand,
            interest=interest,
            mood_valence=soul.mood.valence,
            engagement=appetite_of(engagement),
            form_hint=plan.form_hint,
            roll=roll,
            is_owner=is_owner,
            thresholds=self._brevity_thresholds,
        )

    def guard_reply_length(self, reply: str, demand: AnswerDemand) -> str:
        """Lightly clamp an over-long reply to a simple question (BOB-024 length guard).

        The OPTIONAL safety net behind the brevity bayes: only when the guard is enabled
        AND the message wanted a short answer (``demand`` LOW) does an over-long reply get
        trimmed to its first finished thought via
        :func:`~bob.conversation.brevity.clamp_reply` (no regeneration, never a
        mid-word cut). Disabled (the default) or a non-LOW demand leaves the reply exactly
        as composed — the bayes is the mechanism, this is only a backstop.
        """
        if not self._length_guard_enabled or demand is not AnswerDemand.LOW:
            return reply
        return clamp_reply(reply, max_chars=self._length_guard_max_chars)
