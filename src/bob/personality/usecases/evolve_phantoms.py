# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""EvolvePhantoms — the rare, grounded phantom-preference evolution step (BOB-020).

Hooked onto the heartbeat reflect tick (a slow cadence, beside ``ApplyReflection``
and ``EvolveFascination``), this lets Bob's phantom preferences — his quiet
symphonies (кофе, дождь, книги…) — come *alive* and shift over time, never randomly.
Each run:

1. **Ground a candidate.** A fresh phantom is derived from Bob's REAL inner life —
   the topic he holds the strongest opinion on, or his most recent reflection — via
   the same :class:`~bob.personality.usecases.evolve_fascination.FascinationGrounding`
   seam the fascination flow reads. With no material at all, there is no candidate.
2. **Evolve membership.** The pure
   :func:`~bob.personality.phantom_evolution.evolve_phantoms` kernel decides
   the next set: the grounded candidate may emerge (gated behind a small seeded-RNG
   draw, so the drift is slow), an old phantom fades when the set would overflow its
   bound, and an already-present candidate is a no-op (idempotent — a re-run in the
   same period causes no churn).
3. **Apply + persist.** On a real membership change the live :class:`PersonalityState`
   soul is swapped via :meth:`SOUL.with_phantoms` (a self-evolution step, bumping
   ``experience_count``) and the new set is written through the
   :class:`PhantomProfileWriter` seam so it round-trips across a restart.

Everything is injected — the live state, the persistence seam, the grounding seam,
and a seeded RNG — so the step holds no globals and is deterministic in tests on
fakes (no network).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.personality.phantom_evolution import (
    CHANGE_RATE,
    MAX_PHANTOMS,
    PhantomSignals,
    evolve_phantoms,
)

if TYPE_CHECKING:
    from random import Random

    from bob.kernel.ports import JsonValue
    from bob.personality.state import PersonalityState
    from bob.personality.usecases.evolve_fascination import FascinationGrounding

logger = logging.getLogger(__name__)


class PhantomProfileWriter(Protocol):
    """The narrow persistence seam this step needs: write a JSON artifact.

    A focused view of ``SoulStore`` (interface segregation) — the step only ever
    persists the evolved ``phantom_prefs``, so it depends on this one method rather
    than the full soul-store contract.
    """

    def write_json(self, name: str, data: JsonValue) -> None: ...


class EvolvePhantoms:
    """Rarely refresh Bob's phantom preferences — grounded, slow, bounded, idempotent."""

    def __init__(
        self,
        *,
        state: PersonalityState,
        writer: PhantomProfileWriter,
        grounding: FascinationGrounding,
        rng: Random,
        max_count: int = MAX_PHANTOMS,
        change_rate: float = CHANGE_RATE,
    ) -> None:
        self._state = state
        self._writer = writer
        self._grounding = grounding
        self._rng = rng
        self._max_count = max_count
        self._change_rate = change_rate

    async def run(self) -> None:
        """Run one evolution step: emerge a grounded phantom only when one is due."""
        candidate = await self._ground_candidate()
        current = self._state.soul.phantom_prefs
        signals = PhantomSignals(
            candidate=candidate,
            max_count=self._max_count,
            change_rate=self._change_rate,
        )
        evolved = evolve_phantoms(current, signals, rng=self._rng)
        if evolved == current:  # no membership change → strict no-op.
            return
        self._state.soul = self._state.soul.with_phantoms(evolved)
        self._writer.write_json("phantom_prefs", _phantom_profile(evolved))
        logger.debug("phantom preferences evolved to %r", evolved)

    async def _ground_candidate(self) -> str | None:
        """Derive a fresh phantom from Bob's REAL inner life, or ``None`` if none.

        Prefers the topic he holds the strongest opinion on; falls back to his most
        recent reflection. Never invents — with no material there is no candidate.
        """
        topics = self._grounding.strong_taste_topics()
        if topics:
            return topics[0]
        reflection = await self._grounding.latest_reflection_text()
        if reflection and reflection.strip():
            return reflection.strip()
        return None


def _phantom_profile(phantoms: tuple[str, ...]) -> dict[str, object]:
    """Serialise the phantom set into the persisted ``phantom_prefs`` JSON shape.

    Mirrors the structure Genesis writes and ``_load_soul`` reads back (a
    ``{"preferences": [...]}`` envelope), so an evolved set round-trips across a
    restart.
    """
    return {"preferences": list(phantoms)}
