# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""MoodPerceiver — update Bob's mood from a message + plan its expression (BOB-018/033).

The turn's «how Bob feels + how he chooses to express it» concern in one cohesive
collaborator (extracted from ``HandleMessage`` in BOB-062.6b, wave 2, behavior-preserving):

* :meth:`perceive` runs the Tier-0 sentiment/signal step (:class:`UpdateMoodFromText`) to
  update the in-memory mood, storing the fresh soul snapshot on the SHARED per-boot mood
  holder; and
* :meth:`plan_expression` decides the BOB-018 :class:`ExpressionPlan` (mode + rare add-on
  flags + soft form hint), pure and deterministic by seed.

🔴 The mutable per-boot mood holder (:class:`PersonalityState`) is passed IN per call (never
captured), so ``perceive`` always reads/writes ``HandleMessage``'s CURRENT holder — the
mood accrues across turns exactly as before, even if the holder is re-pointed. 🔴 It shares
the SAME injected ``Random`` as every other turn collaborator, so the per-turn draw order
(**plan** → engagement → verbosity → addressivity → surface/ack) is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.personality.expression import ExpressionSignals, decide_expression
from bob.personality.usecases.update_mood_from_text import TextSignals

if TYPE_CHECKING:
    from random import Random

    from bob.application.usecases.handle_message import PersonalityState
    from bob.kernel.events import MessageReceived
    from bob.personality.expression import ExpressionFreqs, ExpressionPlan
    from bob.personality.soul import SOUL
    from bob.personality.usecases.update_mood_from_text import UpdateMoodFromText

# Each turn perceives one message; a present sender is engaged.
_SINGLE_MESSAGE = 1


class MoodPerceiver:
    """Update Bob's mood from the inbound + plan its expression for one turn."""

    def __init__(
        self,
        *,
        update_mood: UpdateMoodFromText,
        expression_freqs: ExpressionFreqs,
        rng: Random,
    ) -> None:
        self._update_mood = update_mood
        self._expression_freqs = expression_freqs
        self._rng = rng

    async def perceive(
        self, event: MessageReceived, state: PersonalityState
    ) -> SOUL:
        """Update mood from the message text and store the new soul snapshot.

        Passes the soul's mood baseline as the social co-regulation ``target``
        (BOB-033 .3): a warm incoming message tugs mood a proportional fraction back
        toward this baseline, so connection genuinely displaces accumulated low. The
        SHARED per-boot ``state`` holder is passed in (never captured), so the mood is
        read + written on ``HandleMessage``'s current holder.
        """
        signals = TextSignals(text=event.text, message_count=_SINGLE_MESSAGE, present=True)
        new_mood = await self._update_mood.run(
            state.soul.mood, signals, target=state.soul.mood_baseline
        )
        soul = state.soul.with_mood(new_mood)
        state.soul = soul
        return soul

    def plan_expression(
        self, event: MessageReceived, soul: SOUL, *, rng: Random | None = None
    ) -> ExpressionPlan:
        """Decide this turn's expression plan — pure, deterministic by seed (BOB-018).

        Reads the freshly-updated mood + the inbound's shape, draws from the per-turn
        seeded RNG, and returns the plan: mode, the rare add-on flags (carried for later
        beads), and the soft form hint applied to the prompt. 🔴 BOB-066 Срез 2.1: the
        caller threads the turn-local ``TurnScope.rng`` so concurrent chats never share a
        draw stream (INV-4); omitted (a direct unit call) it falls back to the injected rng.
        """
        signals = ExpressionSignals(inbound_text=event.text)
        return decide_expression(
            soul.mood,
            signals,
            rng=rng if rng is not None else self._rng,
            freqs=self._expression_freqs,
        )
