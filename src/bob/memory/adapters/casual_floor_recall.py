# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""CasualFloorRecall — the CASUAL register floor on Bob's SECONDARY recall (BOB-087.C8).

Срез C made the PRIMARY reply-recall register-aware: a casual turn mutes Bob's distilled
``work`` recollections, a dev turn surfaces them at full weight. But recall reaches Bob's
reply through more doors than that one — the grounded-addon callback, the two memory tool
capabilities (``recall_memory`` / ``search_memory``) and the proactive seed each hold their
own :class:`~bob.memory.ports.MemoryRecall`. This decorator closes them, by construction:

* it OVER-FETCHES (:data:`SECONDARY_OVERFETCH_FACTOR` times the caller's ``k``) so the mute has
  something deeper to promote into the freed slots,
* it runs the SAME pure core the primary path runs
  (:func:`~bob.memory.register_pipeline.register_ranked` in
  :attr:`~bob.memory.register.Register.CASUAL`) — no second implementation of the policy,
* and truncates back to the caller's ``k``, so every consumer's contract is unchanged.

🔴 Why the CASUAL FLOOR and not a resolved register. The DEV lift is a PRIMARY-recall
mechanism: it rides together with the first-person provenance directive
(:func:`~bob.personality.voice.recalled_work_directive`), which the voice folds ONLY from the
register-filtered primary pool. A work episode surfacing through a secondary door would
arrive WITHOUT that framing, so Срез C's anti-confabulation guarantee would not hold; and
three of the four doors have no turn to resolve a register FROM (a tool query is the model's
own string, a proactive tick has no incoming message at all). The floor is also the cheapest
honest answer to the Tier-0 economy: the classifier is never consulted here AT ALL.

🔴 Muted, never cut (сквозной Боб). The attenuation is uniform over work episodes, so a
work-dominated pool comes back in its original best-first order — Bob still remembers his
work when work is all there is to remember; it simply stops crowding out his life.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.memory.register import Register
from bob.memory.register_pipeline import register_ranked

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.memory.ports import MemoryRecall, Recalled

__all__ = ["SECONDARY_OVERFETCH_FACTOR", "CasualFloorRecall"]

# How much deeper than the caller's ``k`` the pool is drawn, mirroring the primary path's
# 20-for-5 over-fetch ratio: without spare depth the mute could only re-weight the same top-k
# and never actually free a slot. Cheap — the recall adapter's candidate pool + rerank are
# sized independently of ``k``, so a deeper draw only trims less.
SECONDARY_OVERFETCH_FACTOR = 4


class CasualFloorRecall:
    """A :class:`~bob.memory.ports.MemoryRecall` that holds recall at the CASUAL floor."""

    def __init__(
        self,
        inner: MemoryRecall,
        *,
        overfetch_factor: int = SECONDARY_OVERFETCH_FACTOR,
    ) -> None:
        self._inner = inner
        self._overfetch_factor = overfetch_factor

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        """Return the top-``k`` memories for ``query`` with Bob's work episodes muted.

        Over-fetches from the wrapped recall, applies the CASUAL register ranking (work
        attenuated, deeper non-work promoted, nothing cut) and truncates to ``k``. A
        non-positive ``k`` is the wrapped port's own empty contract — asked for nothing,
        nothing is drawn.
        """
        if k <= 0:
            return ()
        pool = await self._inner.recall(
            query, k=k * self._overfetch_factor, surface_old=surface_old
        )
        return register_ranked(pool, Register.CASUAL, display_k=k)
