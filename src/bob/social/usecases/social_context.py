# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""SocialContext — Bob's per-person read of WHO is writing for a turn (BOB-014/019).

The turn's social-identity concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 2, behavior-preserving). It gathers + evolves the
per-PERSON state that colours a turn: WHO is writing (:class:`Interlocutor`), Bob's LIGHT
first impression of them, his accrued :class:`Relationship` quality (tone warmth +
willingness to compromise), his обида (:class:`SulkState`) state, the negotiation stance
he takes, and the relationship-tone voice line.

Every read is turn-local through arguments (``interlocutor`` / ``soul`` / ``text`` /
``relationship`` are passed in, never held), so this shared-singleton collaborator never
leaks one turn's or one person's state into another. All the state is per-PERSON (about
THEM), so it is loaded/recorded even on a guest turn (never an owner-memory leak).

🔴 :meth:`decide_stance` is PUBLIC — it is shared with the wave-3 VoiceComposer (the
prompt's stance-directive gate reuses the same stance/verdict/zone the record step took).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.personality.negotiation import _clamp_conviction
from bob.personality.profanity import is_directed_hostility
from bob.personality.voice import relationship_tone_directive
from bob.social.relationship import compromise_bias

if TYPE_CHECKING:
    from bob.application.usecases.handle_message import (
        FirstImpressionReader,
        InterlocutorResolver,
        RelationshipReader,
        RosterRecaller,
        SulkReader,
    )
    from bob.conversation.ports import ZoneClassifier
    from bob.kernel.events import MessageReceived
    from bob.kernel.ports import Clock
    from bob.personality.negotiation import Negotiation, NegotiationZone, Stance
    from bob.personality.soul import SOUL
    from bob.personality.taste import Verdict
    from bob.personality.voice import RelationshipToneThresholds
    from bob.social.interlocutor import Interlocutor
    from bob.social.relationship import Relationship
    from bob.social.roster import RosterMember
    from bob.social.sulk import SulkState

logger = logging.getLogger(__name__)


class SocialContext:
    """Perceive + evolve Bob's per-person social read for one turn (BOB-014/019)."""

    def __init__(
        self,
        *,
        perceive_sender: InterlocutorResolver | None,
        first_impression: FirstImpressionReader | None,
        roster: RosterRecaller | None,
        relationship: RelationshipReader | None,
        relationship_tone_thresholds: RelationshipToneThresholds | None,
        sulk: SulkReader | None,
        negotiation: Negotiation,
        zone_classifier: ZoneClassifier,
        clock: Clock,
    ) -> None:
        self._perceive_sender = perceive_sender
        self._first_impression = first_impression
        self._roster = roster
        self._relationship = relationship
        self._relationship_tone_thresholds = relationship_tone_thresholds
        self._sulk = sulk
        self._negotiation = negotiation
        self._zone_classifier = zone_classifier
        self._clock = clock

    async def perceive_interlocutor(
        self, event: MessageReceived
    ) -> Interlocutor | None:
        """Perceive WHO is writing this turn, or ``None`` (no seam wired) (BOB-019).

        Asks the wired perception seam to resolve the inbound into an
        :class:`~bob.social.interlocutor.Interlocutor` (owner / known /
        guest / bot). Unwired (the default) returns ``None`` so the compose path
        adds no who-is-writing line and the turn behaves exactly as before.
        """
        if self._perceive_sender is None:
            return None
        return await self._perceive_sender.resolve(event)

    async def recall_prior_impression(
        self, interlocutor: Interlocutor | None
    ) -> str | None:
        """Recall Bob's LIGHT prior first-impression note for this sender (BOB-019).

        Asks the wired first-impression seam for the stored note of a returning
        sender; a new sender (or no seam / no perceived interlocutor) yields ``None``
        so the compose path adds no recall line. Per-PERSON data, so it is recalled
        even on a guest turn (a guest's own impression is about the guest).
        """
        if self._first_impression is None or interlocutor is None:
            return None
        return await self._first_impression.prior_impression(interlocutor)

    async def recall_roster(
        self, interlocutor: Interlocutor | None
    ) -> tuple[RosterMember, ...]:
        """Recall the roster of who lately turned up in the room, or empty (BOB-080).

        Asks the wired roster seam for the recent joiners so the compose path can let
        Bob NAME them himself when the talk turns to who is around. The seam owns the
        ambient window (only while a fresh newcomer is present, INV-4) and the privacy
        gate (only an OWNER / KNOWN viewer). With no seam wired (the ``social.roster``
        flag off) or no perceived interlocutor this yields an EMPTY roster, so the
        compose path adds no roster line and the turn is byte-identical.
        """
        if self._roster is None:
            return ()
        return await self._roster.recent_roster(self._clock.now(), viewer=interlocutor)

    async def record_first_impression(
        self, interlocutor: Interlocutor | None
    ) -> None:
        """Record Bob's LIGHT first impression of this sender on first contact (BOB-019).

        Best-effort and optional: with no seam wired (or no perceived interlocutor)
        this is a no-op. The grounded note is formed once (the store records once), so
        a returning sender is never overwritten. A flaky store can never break a turn
        that has already replied.
        """
        if self._first_impression is None or interlocutor is None:
            return
        try:
            await self._first_impression.note_first_contact(interlocutor)
        except Exception:
            logger.exception("recording first impression failed (ignored)")

    async def load_relationship(
        self, interlocutor: Interlocutor | None
    ) -> Relationship | None:
        """Load Bob's accrued relationship with this sender, or ``None`` (BOB-014).

        Asks the wired relationship seam for the stored relationship of a known
        sender; a new sender (or no seam / no perceived interlocutor) yields ``None``
        so the turn behaves as a neutral one (no tone/willingness colour). Per-PERSON
        data, so it is loaded even on a guest turn (about the guest).
        """
        if self._relationship is None or interlocutor is None:
            return None
        return await self._relationship.current(interlocutor)

    async def record_relationship(
        self,
        interlocutor: Interlocutor | None,
        soul: SOUL,
        text: str,
        relationship: Relationship | None,
    ) -> None:
        """Evolve + persist Bob's relationship with this sender after the turn (BOB-014).

        Best-effort and optional: with no seam wired (or no perceived interlocutor)
        this is a no-op. The negotiation stance Bob took THIS turn (decided over the
        same relationship-nudged conviction the prompt used), his current mood, and the
        turn's sentiment (read off the mood valence — the mood already reflects the
        perceived sentiment of the message) evolve the relationship via the pure
        :func:`~bob.social.relationship.apply_interaction`. A flaky store
        can never break a turn that has already replied.
        """
        if self._relationship is None or interlocutor is None:
            return
        # Sentiment of the turn: the mood valence already folds in the message's
        # perceived sentiment (UpdateMoodFromText nudges valence by it), so it is the
        # grounded affective signal here — no second classification round-trip.
        sentiment = soul.mood.valence
        stance, _verdict, _zone = self.decide_stance(soul, text, relationship)
        try:
            await self._relationship.record_interaction(
                interlocutor, stance=stance, mood=soul.mood, sentiment=sentiment
            )
        except Exception:
            logger.exception("recording relationship failed (ignored)")

    async def load_sulk(self, interlocutor: Interlocutor | None) -> SulkState | None:
        """Load Bob's обида state toward THIS interlocutor, or ``None`` (BOB-066 2.5).

        With no sulk seam wired (or no perceived interlocutor) returns ``None`` so the
        compose path adds no cold-tone line and the turn behaves exactly as before.
        Otherwise returns the persisted :class:`~bob.social.sulk.SulkState` for this
        sender so the prompt can go cold while Bob is hurt AT THEM — an обида toward
        another participant never chills this reply (🔴 addressed cooling). обида carries
        NO memory and NO soul — only the affect state.
        """
        if self._sulk is None or interlocutor is None or interlocutor.sender_id is None:
            return None
        return await self._sulk.current_for(interlocutor.sender_id)

    async def observe_sulk(
        self, interlocutor: Interlocutor | None, soul: SOUL, text: str
    ) -> None:
        """Fold this person's turn into Bob's обида toward them (BOB-066 2.5).

        Per-person (the owner-gate is gone — Bob can cool toward ANY participant, keyed by
        ``sender_id``). The "low" signal is BOTH this person's relationship warmth (a
        critically cold relationship) AND a DIRECTED hostility flag from
        :func:`~bob.personality.profanity.is_directed_hostility` — so it reacts to
        sustained directed hostility, NOT to casual мат (which is never flagged hostile).
        A warm turn (positive ``warmth_delta``, read off the turn's mood valence)
        accelerates recovery if already hurt. Best-effort: a flaky store can never break
        a turn that already replied.
        """
        if self._sulk is None or interlocutor is None or interlocutor.sender_id is None:
            return
        # This person's relationship warmth this turn (just re-recorded for them); a
        # not-yet-formed relationship reads as neutral 0 (a fresh Bob never sulks blank).
        person_warmth = await self._person_warmth(interlocutor)
        hostile = is_directed_hostility(text)
        # A warm message has positive sentiment; the mood valence folds in the perceived
        # sentiment of the turn (UpdateMoodFromText nudged it), so it is the grounded
        # "how warm was this turn" signal that accelerates отход while sulking.
        warmth_delta = soul.mood.valence
        try:
            await self._sulk.observe(
                sender_id=interlocutor.sender_id,
                person_warmth=person_warmth,
                hostile=hostile,
                warmth_delta=warmth_delta,
                now=self._clock.now(),
            )
        except Exception:
            logger.exception("observing sulk failed (ignored)")

    async def _person_warmth(self, interlocutor: Interlocutor) -> float:
        """This person's relationship warmth for the обида signal, or neutral 0 (BOB-066).

        Reads the freshly-updated relationship for this sender (re-recorded earlier this
        turn) off the relationship seam; a not-yet-formed relationship (or no seam)
        reads as neutral ``0.0`` so a fresh Bob never sulks from a blank read.
        """
        if self._relationship is None:
            return 0.0
        rel = await self._relationship.current(interlocutor)
        return rel.warmth if rel is not None else 0.0

    def decide_stance(
        self, soul: SOUL, text: str, relationship: Relationship | None
    ) -> tuple[Stance, Verdict, NegotiationZone]:
        """Decide Bob's negotiation stance for the turn (BOB-013 + BOB-014).

        Classifies the zone owning ``text`` from the taste verdict + conviction, then
        maps zone + an EFFECTIVE conviction to a :class:`Stance`. The effective
        conviction is the raw conviction lowered by the relationship's
        :func:`~bob.social.relationship.compromise_bias` — a close person
        (high warmth + compatibility) tips a borderline stance from holding ground
        toward agreeing (more willing to compromise), clamped to ``[0, 1]``. Returns
        the stance plus the verdict + zone so the prompt's stance-directive gate can
        reuse them. Pure-ish: no I/O, deterministic for a given soul/text/relationship.
        """
        verdict = soul.taste.score(text)
        conviction = soul.taste.conviction_for(text)
        zone = self._zone_classifier.classify(
            text, taste_verdict=verdict, conviction=conviction
        )
        effective = _clamp_conviction(conviction - compromise_bias(relationship))
        stance = self._negotiation.decide(zone, conviction=effective)
        return stance, verdict, zone

    def relationship_tone(self, relationship: Relationship | None) -> str:
        """The relationship-warmth tone line for this turn, or ``""`` (BOB-014).

        No relationship on record (a new person) or a neutral warmth → no line, so the
        turn keeps the base mood tone. A close relationship reads warmer, a distant one
        more reserved (never rude — relational hostility is the sulk, .2). The warm/
        cool bands are config-tunable via ``relationship_tone_thresholds``.
        """
        if relationship is None:
            return ""
        return relationship_tone_directive(
            relationship.warmth, thresholds=self._relationship_tone_thresholds
        )
