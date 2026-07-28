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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bob.conversation.addressivity import ResponseOutcome
from bob.conversation.response_choice import ResponseIntent
from bob.conversation.thread import _reaction_marker, _render_thread
from bob.conversation.usecases.addressivity_perceiver import _AddressivityDecision
from bob.personality.expression import ExpressionMode
from bob.personality.reaction import reaction_emoji_for

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from bob.application.runtime.events import MessageReceived
    from bob.conversation.response_choice import ResponseChoice
    from bob.conversation.usecases.addressivity_perceiver import AddressivityPerceiver
    from bob.conversation.usecases.decide_response import DecideResponse
    from bob.conversation.usecases.floor_manager import FloorManager
    from bob.conversation.usecases.recall_assembler import RecallAssembler
    from bob.domain.ports import MessageReactor
    from bob.personality.expression import ExpressionPlan
    from bob.personality.soul import SOUL
    from bob.proactivity.self_improvement import RuleModulators
    from bob.social.interlocutor import Interlocutor


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
    ``None`` on the legacy path, where compose replays it itself.
    """

    decision: _AddressivityDecision
    history: Sequence[Mapping[str, object]] | None


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
    ) -> None:
        self._decide_response = decide_response
        self._addressivity = addressivity
        self._floor = floor
        self._essential = essential
        self._assembler = assembler
        self._reactor = reactor
        self._persist = persist
        self._record_owner_activity = record_owner_activity

    async def gate(
        self,
        event: MessageReceived,
        soul: SOUL,
        interlocutor: Interlocutor | None,
        plan: ExpressionPlan,
        interest: float,
        modulators: RuleModulators,
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
        decision = await self._addressivity.decide(event, addressivity_interest)
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
