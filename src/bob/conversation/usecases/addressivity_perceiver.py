# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""AddressivityPerceiver — decide WHO a message is for + whether Bob takes it (BOB-023/025).

The turn's addressivity concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 2, behavior-preserving). Bob perceives WHO a
message is FOR — him, another participant, or no one — from the gateway's structural
signals (``mentions_bob``, a reply targeting Bob's own id, a name-address in the text)
plus whether the recent thread has other participants, then RAISES that per-message
classification to the EFFECTIVE addressivity through the conversation floor (BOB-025 —
an ambient message in a thread where Bob holds a live floor reads as continuity). The
policy decides whether to engage, quietly like-react, or stay SILENT so Bob no longer
barges into every conversation.

🔴 One seeded RNG draw resolves the rare barge-in / like-react branches; the collaborator
shares the SAME injected ``Random`` as every other turn collaborator, so the per-turn
draw order (plan → engagement → verbosity → **addressivity** → surface/ack) is unchanged.
The perceiver depends on the wave-1 :class:`FloorManager` (injected) for the floor raise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.conversation.addressivity import (
    Addressivity,
    ResponseOutcome,
    classify_addressivity,
    decide_response,
    others_present,
)

if TYPE_CHECKING:
    from random import Random

    from bob.application.runtime.events import MessageReceived
    from bob.application.usecases.handle_message import BobUserIdSource, EpisodeReader
    from bob.conversation.addressivity import AddressivityThresholds
    from bob.conversation.conversation_floor import FloorHolder
    from bob.conversation.usecases.floor_manager import FloorManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _AddressivityDecision:
    """The addressivity gate's result for one turn (BOB-023 + BOB-025 floor).

    ``outcome`` is the policy decision (ENGAGE / REACT / SILENT) taken on the
    EFFECTIVE addressivity (per-message raised by the conversation floor when Bob
    holds a live floor). ``per_message`` is the RAW per-message classification — it
    is what ``advance_floor`` reads after the turn (the floor reflects the real
    signals; whether Bob actually replied is tracked separately). ``directed_to_id``
    is the person the turn turned to on a ``DIRECTED_TO_OTHER`` per-message (so the
    floor can pass to them), else ``None``.
    """

    outcome: ResponseOutcome
    per_message: Addressivity
    directed_to_id: int | None


@dataclass(frozen=True, slots=True)
class _AddressivitySignals:
    """This turn's structural addressivity signals (perception, BOB-023/025/049/066).

    The raw, grounded read of WHO the message is for: ``per_message`` is the
    per-message classification; ``effective`` is it raised by the conversation floor
    (continuity); ``others_present`` whether the thread has a third participant;
    ``floor_engaged`` whether the floor actually raised an ambient message to Bob;
    ``reply_to_bob`` whether the inbound replies to Bob's own message;
    ``directed_to_id`` the person a ``DIRECTED_TO_OTHER`` turn turned to (for the
    floor pass), else ``None``; ``floor_holder`` who currently holds the conversation
    floor (``None`` when the floor is inert); and ``floor_participant`` whether THIS
    sender belongs to Bob's live exchange (floor-по-говорящему, BOB-066 .1). These are
    INPUTS — the legacy policy decides the outcome on ``effective`` (BOB-023/025), the
    BOB-049 judge (and the future reflective read) weigh them by meaning.
    """

    per_message: Addressivity
    effective: Addressivity
    others_present: bool
    floor_engaged: bool
    reply_to_bob: bool
    directed_to_id: int | None
    floor_holder: FloorHolder | None
    floor_participant: bool


class AddressivityPerceiver:
    """Perceive who a message is for + decide whether Bob takes the turn (BOB-023/025)."""

    def __init__(
        self,
        *,
        floor: FloorManager,
        episodes: EpisodeReader,
        recent_turns: int,
        bob_user_id_source: BobUserIdSource | None,
        addressivity_thresholds: AddressivityThresholds,
        rng: Random,
    ) -> None:
        self._floor = floor
        self._episodes = episodes
        self._recent_turns = recent_turns
        self._bob_user_id_source = bob_user_id_source
        self._addressivity_thresholds = addressivity_thresholds
        self._rng = rng

    async def decide(
        self, event: MessageReceived, interest: float, *, rng: Random | None = None
    ) -> _AddressivityDecision:
        """Decide whether/how Bob takes THIS turn by addressivity (BOB-023 + BOB-025).

        Classifies who the message is for from the gateway's signals (``mentions_bob``,
        ``reply_to_sender_id`` against Bob's own resolved id, an "Боб, …" name-address
        in the text), reads whether the recent thread has other participants, then —
        when the conversation floor is wired AND enabled — RAISES that per-message
        classification to the EFFECTIVE addressivity: an ``AMBIENT`` message in a thread
        where Bob holds a live floor reads as ``DIRECTED_TO_BOB`` (continuity, BOB-025).
        The policy (:func:`~bob.conversation.addressivity.decide_response`) runs on
        the EFFECTIVE addressivity, so a barge/react/silent decision honours continuity.
        One seeded RNG draw (the same injected RNG, so the turn stays reproducible)
        resolves the rare barge-in / like-react branches. The RAW per-message
        classification is returned alongside the outcome so the floor can advance on the
        real signal after the turn. Floor unwired / disabled → effective == per-message,
        so behaviour is exactly BOB-023.
        """
        signals = await self.signals(event)
        # 🔴 BOB-066 Срез 2.1: the caller threads the turn-local ``TurnScope.rng`` so
        # concurrent chats never share a draw stream (INV-4); omitted → the injected rng.
        roll = (rng if rng is not None else self._rng).random()
        outcome = decide_response(
            signals.effective,
            interest=interest,
            others_present=signals.others_present,
            roll=roll,
            thresholds=self._addressivity_thresholds,
        )
        return _AddressivityDecision(
            outcome=outcome,
            per_message=signals.per_message,
            directed_to_id=signals.directed_to_id,
        )

    async def signals(self, event: MessageReceived) -> _AddressivitySignals:
        """Compute this turn's structural addressivity signals (BOB-023/025/049).

        The shared perception both the legacy policy and the BOB-049 judge read:
        classify who the message is for from the gateway's signals (``mentions_bob``,
        ``reply_to_sender_id`` against Bob's own resolved id, an "Боб, …" name-address),
        read whether the recent thread has other participants, then raise the per-message
        classification to the EFFECTIVE addressivity by the conversation floor (BOB-025 —
        an ambient message in a thread where Bob holds a live floor reads as continuity).
        ``floor_engaged`` records when that raise actually fired (Bob holds the floor);
        ``reply_to_bob`` whether the inbound replies to Bob; ``directed_to_id`` the person
        a ``DIRECTED_TO_OTHER`` turn turned to. These are INPUTS only — the policy decides
        on ``effective``, the judge weighs them by meaning; neither overrides the other.
        """
        present = await self._others_present(event)
        bob_id = self._bob_user_id()
        per_message = classify_addressivity(
            text=event.text,
            mentions_bob=event.mentions_bob,
            reply_to_sender_id=event.reply_to_sender_id,
            bob_user_id=bob_id,
            others_present=present,
        )
        resolution = await self._floor.resolve_effective(
            event.chat_id, per_message, sender_id=event.sender_id
        )
        effective = resolution.effective
        floor_engaged = (
            effective is Addressivity.DIRECTED_TO_BOB
            and per_message is not Addressivity.DIRECTED_TO_BOB
        )
        reply_to_bob = bob_id is not None and event.reply_to_sender_id == bob_id
        directed_to_id = (
            event.reply_to_sender_id
            if per_message is Addressivity.DIRECTED_TO_OTHER
            else None
        )
        return _AddressivitySignals(
            per_message=per_message,
            effective=effective,
            others_present=present,
            floor_engaged=floor_engaged,
            reply_to_bob=reply_to_bob,
            directed_to_id=directed_to_id,
            floor_holder=resolution.holder,
            floor_participant=resolution.participant,
        )

    async def _others_present(self, event: MessageReceived) -> bool:
        """Whether the recent thread has senders OTHER than the current one (BOB-023).

        A light, grounded heuristic over the replayed recent episodes (stored as
        ``"<sender>: <text>\\nbob: <reply>"``): in a 1:1 owner↔Bob thread every label
        matches the current sender → ``False`` (Bob's space, he engages on ambient); a
        third participant appears → ``True`` (mostly stay quiet / like-react on ambient).
        Best-effort: a flaky history read degrades to ``False`` (treat as 1:1 — never
        wrongly silences Bob in his own space).
        """
        try:
            history = await self._episodes.recent_episodes(self._recent_turns)
        except Exception:
            logger.exception("reading history for addressivity failed (ignored)")
            return False
        lines = [
            str(item.get("content", "")) for item in history if item.get("content")
        ]
        return others_present(lines, current_sender_name=event.sender_name)

    def _bob_user_id(self) -> int | None:
        """Bob's own bot ``user_id`` (resolved at startup), or ``None`` (BOB-023).

        Read lazily through the injected seam so the synchronous use-case need not
        know Bob's id at construction; ``None`` (unwired / not yet resolved / the GUPPI
        gateway) degrades gracefully — reply-to-Bob cannot fire, @mention still does.
        """
        if self._bob_user_id_source is None:
            return None
        return self._bob_user_id_source()
