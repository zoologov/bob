# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""reply_delay_inputs — the pure map from answer-demand + interest to the delay knobs.

The DelayedTurn hookup (BOB-066 Срез W, Пласт 3 §natural delay) needs two ``[0, 1]``
inputs the pure :class:`~bob.presence.natural_delay.NaturalDelayPolicy` reads: how
*complex* the reply is (reading + typing time) and how *urgent* it is (a demanded,
time-critical answer comes quicker, relieving the floor). This module holds that one
wiring decision as a deterministic, module-level function so it is unit- and
mutation-testable in isolation, never fattening ``handle()``:

* **urgency** rises with the existing ``classify_answer_demand`` verdict — a HIGH
  demand ("объясни/почему") is answered promptly (floor↓), a LOW one ("ты тут?") is not
  pushed. It maps LOW→0.0, MEDIUM→0.5, HIGH→1.0.
* **complexity** blends that demand with Bob's topic interest — a deep, engaging reply
  reads as more complex (a longer human floor) than a curt, disinterested one.

The clock / the actual wait live in the application coordinator
(:class:`~bob.application.runtime.delayed_turn.DelayedTurn`); this stays pure.
"""

from __future__ import annotations

from bob.conversation.brevity import AnswerDemand

# The answer-demand verdict as a [0, 1] weight: a demanded answer is both more urgent
# (comes quicker) and, blended with interest, a more complex reply.
_DEMAND_WEIGHT: dict[AnswerDemand, float] = {
    AnswerDemand.LOW: 0.0,
    AnswerDemand.MEDIUM: 0.5,
    AnswerDemand.HIGH: 1.0,
}


def _clamp_unit(value: float) -> float:
    """Saturate ``value`` into the closed unit interval ``[0, 1]``."""
    return max(0.0, min(1.0, value))


def reply_delay_inputs(demand: AnswerDemand, interest: float) -> tuple[float, float]:
    """Return the ``(complexity, urgency)`` pair for the natural-delay floor.

    ``urgency`` is the demand weight (LOW→0.0 … HIGH→1.0) — a demanded answer shortens
    the human floor. ``complexity`` is the mean of that weight and the clamped
    ``interest`` — a deep, engaging reply reads as more complex than a curt one. Both
    land in ``[0, 1]``.
    """
    weight = _DEMAND_WEIGHT[demand]
    urgency = weight
    complexity = (weight + _clamp_unit(interest)) / 2.0
    return complexity, urgency
