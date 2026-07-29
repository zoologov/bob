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
    from bob.conversation.room_reading import RoomReading
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
    """

    decision: _AddressivityDecision
    history: Sequence[Mapping[str, object]] | None
    force_web: bool = False


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
        if self._read_the_room is not None and interlocutor is not None:
            return await self._reflective_gate(
                event, soul, interlocutor, interest, rng=rng
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
        """
        del rng  # focal path is RNG-free (INV-1/INV-4); periphery verdict is deterministic
        signals = await self._addressivity.signals(event)
        if signals.per_message is Addressivity.DIRECTED_TO_BOB:
            return _ReplyGate(
                decision=self._floor_signal(signals, ResponseOutcome.ENGAGE),
                history=None,
            )
        reading = await self._read_room(event, soul, interlocutor, signals, interest)
        if reading is None:
            await self.advance_floor_after_turn(
                event,
                self._floor_signal(signals, ResponseOutcome.SILENT),
                bob_replied=False,
            )
            return None
        return await self._act_reflective(event, soul, reading, signals)

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
    ) -> _ReplyGate | None:
        """Carry out the pure reflective verdict for a periphery turn (BOB-066 Срез 2.2).

        REPLY / INITIATE → a :class:`_ReplyGate` (compose+send; ``force_web`` rides the
        gate so the caller forces the existing verify pass on ``wants_web``, C11). REACT →
        set the meaning-chosen emoji + advance the floor. IGNORE / SELF_CHECK / a
        below-salience read → stay silent + advance the floor. Every non-reply advances the
        floor with ``bob_replied=False``; unlike a focal turn there is no owner-activity
        stamp (a periphery reaction is not necessarily the owner interacting).
        """
        verdict = decide_from_reading(reading)
        if verdict.kind is VerdictKind.REPLY:
            return _ReplyGate(
                decision=self._floor_signal(signals, ResponseOutcome.ENGAGE),
                history=None,
                force_web=verdict.force_web,
            )
        if verdict.kind is VerdictKind.REACT:
            emoji = verdict.emoji or reaction_emoji_for(soul.mood)
            await self._react_with_emoji(event, emoji)
            await self.advance_floor_after_turn(
                event,
                self._floor_signal(signals, ResponseOutcome.REACT),
                bob_replied=False,
            )
            return None
        await self.advance_floor_after_turn(
            event, self._floor_signal(signals, ResponseOutcome.SILENT), bob_replied=False
        )
        return None

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
