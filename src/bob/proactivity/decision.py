# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""The proactive decision — urge → probability → seeded sample, gated by governance.

:class:`ProactiveDecider` is the seam the engine calls on a tick: it derives the
local hour from an injected :class:`Clock`, scores the :class:`UrgeModel`, maps
that urge to a fire probability via a monotonic logistic curve, draws once from an
**injected seeded RNG**, and then lets :class:`Governance` veto the result. It is
pure given the injected clock value and RNG — no ``datetime.now()`` and no global
``random`` — so a fixed seed makes the decision fully reproducible in tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.proactivity.urge import UrgeModel

if TYPE_CHECKING:
    from random import Random

    from bob.kernel.ports import Clock
    from bob.personality.mood import Mood
    from bob.proactivity.governance import Governance, ProactiveHistory

# Logistic mapping urge → p(speak). The midpoint sits at this urge (where p=0.5)
# and the steepness controls how sharply probability swings around it. Tunable.
_LOGISTIC_MIDPOINT = 0.5
_LOGISTIC_STEEPNESS = 8.0


def urge_to_probability(urge: float) -> float:
    """Map an urge in ``[0, 1]`` to a fire probability in ``(0, 1)``, monotonically.

    A logistic curve: low urge yields a small (non-zero) chance, high urge a large
    (sub-one) chance, and the mapping is strictly increasing in ``urge``.
    """
    return 1.0 / (1.0 + math.exp(-_LOGISTIC_STEEPNESS * (urge - _LOGISTIC_MIDPOINT)))


@dataclass(frozen=True, slots=True)
class ProactiveDecider:
    """Decide whether Bob speaks proactively now (urge → seeded sample → veto)."""

    clock: Clock
    governance: Governance
    urge_model: UrgeModel = field(default_factory=UrgeModel)

    def should_speak(
        self,
        *,
        mood: Mood,
        silence_seconds: float,
        salience: float,
        social_energy: float,
        history: ProactiveHistory,
        rng: Random,
    ) -> bool:
        """Return whether Bob fires a proactive message on this tick.

        The injected ``clock`` supplies "now" (for the circadian hour and the
        governance vetoes) and the injected ``rng`` supplies the single stochastic
        draw, so the decision is deterministic given those two inputs. Governance
        is checked first: a veto means silence regardless of the urge.
        """
        now = self.clock.now()
        if not self.governance.allows(now=now, history=history):
            return False
        urge = self.urge_model.urge(
            mood=mood,
            silence_seconds=silence_seconds,
            salience=salience,
            time_of_day_local=now.hour,
            social_energy=social_energy,
        )
        probability = urge_to_probability(urge)
        return rng.random() < probability
