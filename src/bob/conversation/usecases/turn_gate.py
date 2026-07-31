# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""TurnGate — decide WHETHER/HOW Bob takes a turn: reply, react, or stay silent.

The turn's response-gate concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 4, behavior-preserving). A thin coordinator over
the already-extracted turn collaborators — the :class:`AddressivityPerceiver`
(perception + the legacy policy), the injected semantic judge
(:class:`~bob.conversation.usecases.decide_response.DecideResponse`, BOB-049), the
:class:`FloorManager` (advance the conversation floor) and the reliability
:class:`EssentialRunner` (retry the ESSENTIAL judgment) — plus two callbacks back into
the use-case (persist the user's turn + stamp owner activity).

The gate returns ``None`` when the turn was already fully handled as a NON-reply (a
silent / react / ignore early-out — persisted where required + floor-advanced), or a
:class:`_ReplyGate` when Bob should compose+send (guest restrictions stay on the compose
path, untouched here).

🔴 The conversation floor advances on ALL branches — SILENT / REACT / REACT_ONLY /
judge-REACT / judge-IGNORE advance inside the gate with ``bob_replied=False``; the
happy-path reply advances in the caller with ``bob_replied=True`` (an essential failure
never reaches an advance, exactly as before). 🔴 One seeded RNG draw lives in the legacy
policy (via the shared :class:`AddressivityPerceiver`), so the per-turn draw order
(plan → engagement → verbosity → **addressivity** → surface/ack) is unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bob.conversation.addressivity import Addressivity, ResponseOutcome
from bob.conversation.response_choice import ResponseIntent
from bob.conversation.room_verdict import VerdictKind, decide_from_reading
from bob.conversation.thread import _reaction_marker, _render_thread
from bob.conversation.usecases.addressivity_perceiver import _AddressivityDecision
from bob.personality.expression import ExpressionMode
from bob.personality.reaction import reaction_emoji_for

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from random import Random

    from bob.application.runtime.events import MessageReceived
    from bob.conversation.conversation_floor import FloorHolder
    from bob.conversation.response_choice import ResponseChoice
    from bob.conversation.room_reading import RoomMood, RoomReading
    from bob.conversation.usecases.addressivity_perceiver import (
        AddressivityPerceiver,
        _AddressivitySignals,
    )
    from bob.conversation.usecases.decide_response import DecideResponse
    from bob.conversation.usecases.floor_manager import FloorManager
    from bob.conversation.usecases.read_the_room import ReadTheRoom
    from bob.conversation.usecases.recall_assembler import RecallAssembler
    from bob.personality.expression import ExpressionPlan
    from bob.personality.ports import MessageReactor
    from bob.personality.soul import SOUL
    from bob.proactivity.self_improvement import RuleModulators
    from bob.social.interlocutor import Interlocutor

logger = logging.getLogger(__name__)


def _directed_engage(signals: _AddressivitySignals) -> bool:
    """Would the LEGACY addressivity policy answer this turn deterministically? (BOB-066 fix).

    Mirrors the ENGAGE set of :func:`~bob.conversation.addressivity.decide_response` read on the
    EFFECTIVE addressivity: a turn directed AT Bob — a RAW «Боб,»/@mention/reply-to-Bob OR a
    FLOOR-CONTINUITY raise (Bob holds a live floor with this sender, so ``effective`` is
    ``DIRECTED_TO_BOB``) — is always answered; and an ``AMBIENT`` message in Bob's OWN 1:1 space
    (no other participant) is his to take. Everything else — a genuine MULTI-PARTY ambient or a
    directed-to-another turn — is left to the reflective read (discretionary). This is the
    deterministic-reply set the reflective focus check must honour so a plain follow-up to Bob's
    question / a message in his own space is never silently dropped.
    """
    return signals.effective is Addressivity.DIRECTED_TO_BOB or (
        signals.effective is Addressivity.AMBIENT and not signals.others_present
    )


@dataclass(frozen=True, slots=True)
class _JudgedTurn:
    """The semantic judge's outcome for one turn + the pieces the flow reuses (BOB-049).

    ``choice`` is the judge's :class:`ResponseChoice` (REPLY / REACT / IGNORE +
    emoji); ``floor`` carries the RAW per-message addressivity the conversation floor
    advances on after the turn; ``history`` is the CURRENT person's per-person thread
    already replayed for the judgment, threaded into the REPLY compose path so it is
    not re-read.
    """

    choice: ResponseChoice
    floor: _AddressivityDecision
    history: Sequence[Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class _ReplyGate:
    """A turn that PASSED the response gate as a REPLY (BOB-049): compose+send next.

    ``decision`` is the floor signal the turn advances on after Bob replies;
    ``history`` is the CURRENT person's per-person thread already replayed for the
    judgment (the judge REPLY path), threaded into compose so it is not re-read —
    ``None`` on the legacy path, where compose replays it itself. ``force_web`` is the
    reflective autonomous-lookup flag (BOB-066 Срез 2.2, C11): when a periphery read set
    ``wants_web`` it rides here so the caller FORCES the existing verify pass — ``False``
    on every other path (focus / judge / legacy), where the verify judge decides.
    ``room_mood`` is the reflective read's room atmosphere (BOB-066 Срез W.2, Пласт 4): it
    rides ONLY on a PERIPHERY reflective REPLY so the caller can colour Bob's tone + appetite
    by the room BY VALUE — ``None`` on every other path (focus / judge / legacy has no read),
    so those turns are byte-identical.
    """

    decision: _AddressivityDecision
    history: Sequence[Mapping[str, object]] | None
    force_web: bool = False
    room_mood: RoomMood | None = None


class _EssentialRunner(Protocol):
    """The reliability seam: run an ESSENTIAL LLM step with bounded retry (BOB-049 .3)."""

    async def run[T](
        self, operation: Callable[[], Awaitable[T]], *, step: str
    ) -> T: ...


class _Persist(Protocol):
    """The persist seam (injected — the conversation gate stores no persistence policy)."""

    async def __call__(
        self,
        event: MessageReceived,
        reply: str,
        soul: SOUL,
        *,
        bob_message_id: int | None = None,
    ) -> None: ...


class _OwnerActivity(Protocol):
    """The owner-activity seam: stamp that the owner interacted this turn (best-effort)."""

    async def __call__(self) -> None: ...


class _BargeCeiling(Protocol):
    """The share-of-voice ceiling seam on an ambient barge (BOB-066 Срез W, Пласт 3).

    Realised by :class:`~bob.application.runtime.share_of_voice_gate.ShareOfVoiceGate`.
    Given the turn's ``chat_id``, whether Bob was ``focused`` (directly addressed), the
    caller's un-ceiled ``base_probability`` of barging in, and a turn-local ``draw``,
    returns whether Bob may barge into this ambient turn. 🔴 Only the AMBIENT (periphery)
    barge is gated — a focused turn short-circuits ABOVE the gate and is never consulted
    (INV-1). ``None`` (unwired — the ``presence.rhythm`` flag off) leaves the periphery
    REPLY un-throttled, byte-identical to before the rhythm layer.
    """

    async def admits_barge(
        self, *, chat_id: int, focused: bool, base_probability: float, draw: float
    ) -> bool: ...


# Bob's persisted half of a non-reply turn (BOB-049), so a follow-up keeps the
# per-person thread (BOB-045): IGNORE writes "(промолчал)", REACT "(реакция: <emoji>)".
# Russian persona voice (project language); Cyrillic look-alikes are intentional.
_SILENT_MARKER = "(промолчал)"


# Map the judge's intent to the legacy outcome the conversation floor advances on
# (BOB-049): the floor reads per_message + bob_replied, so this is the cosmetic
# outcome label only — REPLY engages, REACT like-reacts, IGNORE stays silent.
_OUTCOME_FOR_INTENT: dict[ResponseIntent, ResponseOutcome] = {
    ResponseIntent.REPLY: ResponseOutcome.ENGAGE,
    ResponseIntent.REACT: ResponseOutcome.REACT,
    ResponseIntent.IGNORE: ResponseOutcome.SILENT,
}

# The tilted addressivity interest reads as a probability in the closed unit interval:
# the policy interest plus the self-improvement ADDRESSIVITY_BIAS nudge both live in
# ``[0, 1]``.
_MIN_INTEREST = 0.0
_MAX_INTEREST = 1.0


def _clamp_unit(value: float) -> float:
    """Saturate ``value`` into the closed unit interval (a bounded interest/bias)."""
    return max(_MIN_INTEREST, min(_MAX_INTEREST, value))


def _floor_holder_label(holder: FloorHolder | None) -> str:
    """Render the floor holder as a compact label for the reflective prompt (BOB-066 2.2).

    ``None`` (the floor is inert / unresolved) → ``"none"``; otherwise the holder enum's
    value (``"bob"`` / ``"other"`` / ``"idle"``) — a plain string hint the reflection
    weighs, never a rule.
    """
    return holder.value if holder is not None else "none"


class TurnGate:
    """Decide whether/how Bob takes this turn: reply, react, or stay silent (BOB-049)."""

    def __init__(
        self,
        *,
        decide_response: DecideResponse | None,
        addressivity: AddressivityPerceiver,
        floor: FloorManager,
        essential: _EssentialRunner,
        assembler: RecallAssembler,
        reactor: MessageReactor | None,
        persist: _Persist,
        record_owner_activity: _OwnerActivity,
        read_the_room: ReadTheRoom | None = None,
        barge_ceiling: _BargeCeiling | None = None,
    ) -> None:
        self._decide_response = decide_response
        self._addressivity = addressivity
        self._floor = floor
        self._essential = essential
        self._assembler = assembler
        self._reactor = reactor
        self._persist = persist
        self._record_owner_activity = record_owner_activity
        self._read_the_room = read_the_room
        self._barge_ceiling = barge_ceiling

    async def gate(  # noqa: PLR0911 — a flat three-path dispatch (reflective / judge / legacy), one early-out per branch, no logic to extract
        self,
        event: MessageReceived,
        soul: SOUL,
        interlocutor: Interlocutor | None,
        plan: ExpressionPlan,
        interest: float,
        modulators: RuleModulators,
        *,
        rng: Random | None = None,
        series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
        ambient_reading: RoomReading | None = None,
    ) -> _ReplyGate | None:
        """Decide whether/how Bob takes this turn (BOB-049 judge, or legacy fallback).

        With the semantic judge wired (the LIVE path) Bob UNDERSTANDS the message and
        chooses REPLY / REACT / IGNORE — the structural signals are INPUTS he weighs, not
        deciders, and the decision holds for ANY interlocutor (authz orthogonal). A
        non-REPLY (REACT / IGNORE) is fully handled here — it persists the user's turn (so
        a follow-up keeps the per-person thread, BOB-045) and advances the floor — and
        returns ``None`` so the caller stops. A REPLY returns a :class:`_ReplyGate` so the
        caller composes+sends (guest restrictions intact). Unwired (the default) OR no
        sender perceived → the legacy addressivity ladder (BOB-023/025) + the BOB-018
        REACT_ONLY form gate run exactly as before (their silent/react early-outs return
        ``None`` WITHOUT persisting, as today).
        """
        # 🔴 BOB-066 Срез 2.2: the reflective «два-скорости-внимания» split sits at the
        # VERY TOP, ДО судьи — when the reflective reader is wired AND a sender is
        # perceived, Bob takes the focus/periphery fork (INV-1 lives here). Unwired (the
        # default) OR no sender → the BOB-049 judge / legacy paths run exactly as before.
        # 🔴 BOB-072: a PRE-COMPUTED ``ambient_reading`` (the intake worker's holistic batch
        # stream-read) also takes the reflective fork — even when the per-message reflective
        # reader is unwired — so the batch verdict is applied through the SAME apply path
        # (focal short-circuit + persist/floor for all, INV-1/INV-S2).
        take_reflective = interlocutor is not None and (
            self._read_the_room is not None or ambient_reading is not None
        )
        if take_reflective and interlocutor is not None:
            return await self._reflective_gate(
                event,
                soul,
                interlocutor,
                interest,
                rng=rng,
                series_ceiling=series_ceiling,
                ambient_reading=ambient_reading,
            )
        if self._decide_response is not None and interlocutor is not None:
            judged = await self._judge(event, soul, interlocutor)
            if judged.choice.intent is not ResponseIntent.REPLY:
                await self._act_non_reply(event, soul, judged.choice, judged.floor)
                return None
            return _ReplyGate(decision=judged.floor, history=judged.history)
        # Legacy addressivity path (BOB-023/025). ADDRESSIVITY self-improvement tilt
        # (BOB-028 .3): an APPROVED ADDRESSIVITY_BIAS rule softly RAISES the effective
        # interest the policy reads — a bounded nudge (clamped to [0, 1]) on TOP of the
        # decision, never a base override and never able to silence Bob. No rule → unchanged.
        addressivity_interest = _clamp_unit(interest + modulators.addressivity_bias)
        # 🔴 BOB-066 Срез 2.1: thread the turn-local ``TurnScope.rng`` into the legacy
        # addressivity draw (INV-4 — concurrent chats never share a draw stream).
        decision = await self._addressivity.decide(
            event, addressivity_interest, rng=rng
        )
        if decision.outcome is ResponseOutcome.SILENT:
            await self.advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        if decision.outcome is ResponseOutcome.REACT and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self.advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        # React-only (BOB-018): when a reactor is wired and the plan picks REACT_ONLY, Bob
        # acknowledges with a native mood emoji INSTEAD of composing a reply — no LLM call,
        # no rich final, no episode (there is no reply text). It is still real engagement,
        # so the owner-activity marker fires. Unwired, the plan falls back to a full reply.
        if plan.mode is ExpressionMode.REACT_ONLY and self._reactor is not None:
            await self._react_only(event, soul)
            await self._record_owner_activity()
            await self.advance_floor_after_turn(event, decision, bob_replied=False)
            return None
        return _ReplyGate(decision=decision, history=None)

    async def _reflective_gate(
        self,
        event: MessageReceived,
        soul: SOUL,
        interlocutor: Interlocutor,
        interest: float,
        *,
        rng: Random | None,
        series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
        ambient_reading: RoomReading | None = None,
    ) -> _ReplyGate | None:
        """The «два-скорости-внимания» fork (BOB-066 Срез 2.2 Пласт 1).

        🔴 FOCUS (INV-1): a RAW ``DIRECTED_TO_BOB`` (mention / reply-to-Bob / «Боб,») short-
        circuits to a DETERMINISTIC :class:`_ReplyGate` — bypassing the reflective read, the
        RNG and the share-of-voice ceiling. Direct address is answered OR (on a downstream
        generation failure) becomes an honest GUPPI notice, NEVER silence. ``rng`` is
        accepted for signature parity but deliberately UNUSED here — the focal path takes no
        random draw (that IS the invariant).

        PERIPHERY (ambient / directed-to-other, INCLUDING floor-continuity as a strong prior
        the reflection may override): one rich reflective read → the pure
        :func:`~bob.conversation.room_verdict.decide_from_reading` verdict. A read FAILURE
        safe-defaults to a silent IGNORE (advance the floor, NO GUPPI notice — this is not
        the focal guarantee), never Bob acting from a guessed read.

        🔴 The FOCAL path is RNG-free (INV-1/INV-4): it returns ABOVE the reflective read and
        the share-of-voice ceiling, so ``rng`` is drawn ONLY on the periphery, and ONLY when
        the ambient-barge ceiling is wired (``presence.rhythm``) — otherwise no draw is taken
        and behaviour is byte-identical.
        """
        signals = await self._addressivity.signals(event)
        if _directed_engage(signals):
            # 🔴 INV-1 (raw direct address) + the legacy ENGAGE set (BOB-066 fix): a turn the
            # legacy addressivity policy answers deterministically — a RAW «Боб,»/@mention/
            # reply-to-Bob, a FLOOR-CONTINUITY turn (``effective`` raised to DIRECTED_TO_BOB
            # because Bob holds a live floor with this sender), OR a 1:1/own-space ambient (no
            # other participant) — is answered ABOVE the reflective read, the RNG and the
            # series/share-of-voice ceilings, so it is NEVER silently dropped. Only a genuine
            # MULTI-PARTY ambient / directed-to-other falls through to the reflective read below.
            # Restores the pre-activation "answer a plain follow-up to my question / in my own
            # space" the raw-only focus check regressed (found in live owner+Bob validation).
            return _ReplyGate(
                decision=self._floor_signal(signals, ResponseOutcome.ENGAGE),
                history=None,
            )
        # 🔴 BOB-072: when the intake worker supplied a pre-computed reading (the holistic batch
        # stream-read over the whole ambient burst), apply it DIRECTLY — no per-message read.
        # The safe all-IGNORE fallback the batch reader returns on failure lands here too, so a
        # garbled/absent batch read still persists the incoming (Seam B) via _advance_silent.
        reading = (
            ambient_reading
            if ambient_reading is not None
            else await self._read_room(event, soul, interlocutor, signals, interest)
        )
        if reading is None:
            # 🔴 BOB-071 Seam B: a safe silent IGNORE on a read failure still persists the
            # incoming turn (via _advance_silent) so the thread stays intact.
            await self._advance_silent(event, soul, signals)
            return None
        return await self._act_reflective(
            event, soul, reading, signals, rng=rng, series_ceiling=series_ceiling
        )

    async def _read_room(
        self,
        event: MessageReceived,
        soul: SOUL,
        interlocutor: Interlocutor,
        signals: _AddressivitySignals,
        interest: float,
    ) -> RoomReading | None:
        """Run the periphery reflective read, or ``None`` on any failure (safe IGNORE).

        Assembles the SHARED author-labelled thread (BOB-058) + the structural / floor
        hints + Bob's topic interest into the read context and delegates to the injected
        :class:`ReadTheRoom`. 🔴 The reader RAISES on a model/parse failure; here that is
        caught and mapped to ``None`` so the periphery turn stays silent (INV-2 — a
        peripheral reflection failure is a tidy skip, not a GUPPI notice).
        """
        assert self._read_the_room is not None  # guarded by the caller
        history = await self._assembler.replay_recent_thread(interlocutor)
        try:
            return await self._read_the_room.read(
                text=event.text,
                interlocutor=interlocutor,
                recent_thread=_render_thread(history),
                mood_tone=soul.mood.tone(),
                addressivity=signals.per_message,
                mentions_bob=event.mentions_bob,
                reply_to_bob=signals.reply_to_bob,
                others_present=signals.others_present,
                floor_engaged=signals.floor_engaged,
                floor_holder=_floor_holder_label(signals.floor_holder),
                floor_participant=signals.floor_participant,
                interest=interest,
            )
        except Exception:
            logger.exception("reflective read failed (periphery → silent ignore)")
            return None

    async def _act_reflective(
        self,
        event: MessageReceived,
        soul: SOUL,
        reading: RoomReading,
        signals: _AddressivitySignals,
        *,
        rng: Random | None,
        series_ceiling: ResponseOutcome = ResponseOutcome.ENGAGE,
    ) -> _ReplyGate | None:
        """Carry out the pure reflective verdict for a periphery turn (BOB-066 Срез 2.2).

        REPLY / INITIATE → a :class:`_ReplyGate` (compose+send; ``force_web`` rides the
        gate so the caller forces the existing verify pass on ``wants_web``, C11) — UNLESS
        the share-of-voice ceiling damps this ambient barge to silence (BOB-066 Срез W).
        REACT → set the meaning-chosen emoji + advance the floor. IGNORE / SELF_CHECK / a
        below-salience read → stay silent + advance the floor. Every non-reply advances the
        floor with ``bob_replied=False``; unlike a focal turn there is no owner-activity
        stamp (a periphery reaction is not necessarily the owner interacting).

        🔴 BOB-066 Срез W.2 (batch top-k): the ``series_ceiling`` CAPS the ambient outcome —
        when several inbound settle in one intake window, only one reply + one like land, so a
        message the series budget marked REACT downgrades a REPLY verdict to a like, and a
        SILENT ceiling stays quiet. ``ENGAGE`` (the default / a single-message window) is no
        cap. The focal path never reaches here (INV-1 short-circuits above), so a direct
        address is never dropped by the budget.
        """
        verdict = decide_from_reading(reading)
        if verdict.kind is VerdictKind.REPLY:
            return await self._act_reply_verdict(
                event, soul, reading, signals, rng=rng, series_ceiling=series_ceiling
            )
        # A REACT verdict sets the meaning-chosen emoji — UNLESS the series budget exhausted this
        # message to SILENT. IGNORE / SELF_CHECK / a SILENT-capped REACT stay silent.
        if verdict.kind is VerdictKind.REACT and series_ceiling is not ResponseOutcome.SILENT:
            await self._react_turn(event, soul, signals, verdict.emoji)
            return None
        await self._advance_silent(event, soul, signals)
        return None

    async def _act_reply_verdict(
        self,
        event: MessageReceived,
        soul: SOUL,
        reading: RoomReading,
        signals: _AddressivitySignals,
        *,
        rng: Random | None,
        series_ceiling: ResponseOutcome,
    ) -> _ReplyGate | None:
        """Carry out a periphery REPLY verdict under the rhythm + series ceilings (W / W.2).

        🔴 The two ceilings CAP the ambient barge, in order: the batch top-k ``series_ceiling``
        (SILENT → stay quiet; REACT → downgrade to a like — a REPLY reading has no chosen emoji,
        so a mood emoji stands in), then the share-of-voice ceiling (a hogged-airtime barge is
        damped to silence). Passing both → a :class:`_ReplyGate` that surfaces the room mood so
        the caller colours Bob's tone + appetite by the room (BOB-066 Срез W.2, Пласт 4).
        """
        if series_ceiling is ResponseOutcome.SILENT:
            await self._advance_silent(event, soul, signals)
            return None
        if series_ceiling is ResponseOutcome.REACT:
            await self._react_turn(event, soul, signals, reading.emoji)
            return None
        if not await self._admits_ambient_barge(event, reading, rng):
            await self._advance_silent(event, soul, signals)
            return None
        return _ReplyGate(
            decision=self._floor_signal(signals, ResponseOutcome.ENGAGE),
            history=None,
            force_web=decide_from_reading(reading).force_web,
            room_mood=reading.room_mood,
        )

    async def _react_turn(
        self,
        event: MessageReceived,
        soul: SOUL,
        signals: _AddressivitySignals,
        emoji: str | None,
    ) -> None:
        """Set a like (chosen or mood emoji), persist the user's turn, advance the floor (react).

        🔴 BOB-071 Seam B: the user's turn is persisted (``(реакция: <emoji>)``) exactly like
        the judge-path :meth:`_act_non_reply` on REACT, so a reflective REACT keeps the thread
        intact in ``episodic_log`` instead of silently dropping the incoming message.
        """
        used_emoji = emoji or reaction_emoji_for(soul.mood)
        await self._react_with_emoji(event, used_emoji)
        await self._persist(event, _reaction_marker(used_emoji), soul)
        await self.advance_floor_after_turn(
            event, self._floor_signal(signals, ResponseOutcome.REACT), bob_replied=False
        )

    async def _advance_silent(
        self, event: MessageReceived, soul: SOUL, signals: _AddressivitySignals
    ) -> None:
        """Persist the user's silent turn + advance the floor (bob_replied=False).

        🔴 BOB-071 Seam B: a reflective IGNORE persists the incoming message (``(промолчал)``)
        exactly like the judge-path :meth:`_act_non_reply` on IGNORE — «читаю комнату, но помню
        разговор». Without it a genuinely-ambient participant turn never entered ``episodic_log``
        and the thread broke. Unlike the judge path there is NO owner-activity stamp: a periphery
        read is not necessarily the owner interacting.
        """
        await self._persist(event, _SILENT_MARKER, soul)
        await self.advance_floor_after_turn(
            event, self._floor_signal(signals, ResponseOutcome.SILENT), bob_replied=False
        )

    async def _admits_ambient_barge(
        self, event: MessageReceived, reading: RoomReading, rng: Random | None
    ) -> bool:
        """Whether the share-of-voice ceiling admits THIS ambient barge (BOB-066 Срез W).

        Consulted ONLY on a periphery REPLY verdict (a focal turn never reaches here — INV-1
        short-circuits above). Unwired ceiling OR no turn-local ``rng`` → always ``True`` and
        NO draw is taken, so the periphery stays byte-identical to before the rhythm layer.
        When wired, the reading's ``salience`` is the un-ceiled base p(barge); the gate scales
        it by Bob's per-chat share of voice and compares it to the turn-local draw (``focused``
        is ``False`` — this branch is ambient by construction).
        """
        if self._barge_ceiling is None or rng is None:
            return True
        return await self._barge_ceiling.admits_barge(
            chat_id=event.chat_id,
            focused=False,
            base_probability=reading.salience,
            draw=rng.random(),
        )

    def _floor_signal(
        self, signals: _AddressivitySignals, outcome: ResponseOutcome
    ) -> _AddressivityDecision:
        """Build the floor-advance signal for a reflective turn from the raw signals.

        The conversation floor advances on the RAW ``per_message`` + ``directed_to_id``
        (whether Bob actually replied is tracked separately by ``bob_replied``); the
        ``outcome`` is the cosmetic label only, so this is a thin, DRY translation shared by
        the focus and periphery branches.
        """
        return _AddressivityDecision(
            outcome=outcome,
            per_message=signals.per_message,
            directed_to_id=signals.directed_to_id,
        )

    async def _judge(
        self, event: MessageReceived, soul: SOUL, interlocutor: Interlocutor
    ) -> _JudgedTurn:
        """Ask the semantic judge how Bob takes this turn (BOB-049, the LIVE path).

        Assembles the turn's context — the message, the sender as social context, the
        SHARED recent thread of the whole topic (BOB-058 .1: all participants, author-
        labeled, so Bob holds the multi-party thread), the structural HINTS and the mood
        tone — and delegates
        the single semantic decision to the injected :class:`DecideResponse`. The judge
        raises on failure (the fault-tolerant path is BOB-049 .3); here we assume success.
        Returns the choice plus the floor signal (RAW per-message addressivity) and the
        already-replayed history so a REPLY does not re-read it.
        """
        assert self._decide_response is not None  # guarded by the caller
        decide_response = self._decide_response
        signals = await self._addressivity.signals(event)
        history = await self._assembler.replay_recent_thread(interlocutor)
        # ESSENTIAL step (BOB-049 .3): the semantic judgment is retry-wrapped — a flaky
        # judge call retries with backoff, then (if still failing) raises
        # _EssentialStepError so the turn falls back to the honest GUPPI outage notice
        # rather than a guessed default. A SUCCESSFUL REACT/IGNORE is a genuine choice,
        # not a failure (no retry, no notice).
        choice = await self._essential.run(
            lambda: decide_response.decide(
                text=event.text,
                interlocutor=interlocutor,
                recent_thread=_render_thread(history),
                mentions_bob=event.mentions_bob,
                reply_to_bob=signals.reply_to_bob,
                addressivity=signals.per_message,
                others_present=signals.others_present,
                floor_engaged=signals.floor_engaged,
                mood_tone=soul.mood.tone(),
            ),
            step="response judgment",
        )
        floor = _AddressivityDecision(
            outcome=_OUTCOME_FOR_INTENT[choice.intent],
            per_message=signals.per_message,
            directed_to_id=signals.directed_to_id,
        )
        return _JudgedTurn(choice=choice, floor=floor, history=history)

    async def _act_non_reply(
        self,
        event: MessageReceived,
        soul: SOUL,
        choice: ResponseChoice,
        decision: _AddressivityDecision,
    ) -> None:
        """Carry out a REACT or IGNORE turn: persist the user's turn + advance (BOB-049).

        🔴 The user's turn is persisted in BOTH branches so a follow-up always has the
        prior turn in the per-person thread (BOB-045): REACT records ``bob: (реакция:
        <emoji>)`` and sets the meaning-chosen emoji on the inbound, IGNORE records
        ``bob: (промолчал)``. Only the episodic conversation record is written — never an
        owner FACT (no fact extraction here), so a guest turn never enters owner memory
        (BOB-019). The floor advances with ``bob_replied=False`` and the owner-activity
        marker fires (the owner did interact this turn). No reply text → no typing
        indicator / router call.
        """
        if choice.intent is ResponseIntent.REACT:
            emoji = choice.emoji or reaction_emoji_for(soul.mood)
            await self._react_with_emoji(event, emoji)
            await self._persist(event, _reaction_marker(emoji), soul)
        else:
            await self._persist(event, _SILENT_MARKER, soul)
        await self.advance_floor_after_turn(event, decision, bob_replied=False)
        await self._record_owner_activity()

    async def _react_with_emoji(self, event: MessageReceived, emoji: str) -> None:
        """Set the meaning-chosen emoji reaction on the inbound, best-effort (BOB-049).

        The judge picked the emoji BY MEANING (replacing the BOB-018 mood→emoji table as
        the source). When a reactor is wired it is set on the user's message; unwired the
        decision still stands (the turn persists as a reaction) but no native reaction is
        sent — a clean no-op, so the path stays backward-compatible.
        """
        if self._reactor is None:
            return
        await self._reactor.react(
            chat_id=event.chat_id, message_id=event.message_id, emoji=emoji
        )

    async def _react_only(self, event: MessageReceived, soul: SOUL) -> None:
        """Set a native mood emoji reaction on the inbound (BOB-018 react-only).

        Picks a standard-reaction emoji from Bob's current mood and asks the wired
        reactor to set it on the user's message. The reaction is best-effort (the
        adapter degrades to a brief ack and never raises), so this never breaks the
        turn. Called only when a reactor is wired and the plan picked REACT_ONLY.
        """
        assert self._reactor is not None  # guarded by the caller
        emoji = reaction_emoji_for(soul.mood)
        await self._reactor.react(
            chat_id=event.chat_id, message_id=event.message_id, emoji=emoji
        )

    async def advance_floor_after_turn(
        self,
        event: MessageReceived,
        decision: _AddressivityDecision,
        *,
        bob_replied: bool,
    ) -> None:
        """Advance the conversation floor after a turn (BOB-025) via :class:`FloorManager`.

        A thin translation from this turn's application event + decision to the
        collaborator's primitive call — kept as one DRY point because the advance fires on
        ALL branches (SILENT / REACT / react-only / happy-path).
        """
        await self._floor.advance_after_turn(
            chat_id=event.chat_id,
            sender_id=event.sender_id,
            per_message=decision.per_message,
            directed_to_id=decision.directed_to_id,
            bob_replied=bob_replied,
        )
