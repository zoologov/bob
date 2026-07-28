# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=application

"""Fascination source adapters — the live seams the fascination flow reads (BOB-020).

Two thin application adapters that keep :class:`EvolveFascination` and the compose
path pure of storage/state plumbing:

* :class:`RepoFascinationGrounding` realises
  :class:`~bob.personality.usecases.evolve_fascination.FascinationGrounding`: Bob's
  REAL grounding material for a fascination pick — his most recent reflection (via
  the :class:`~bob.personality.ports.ReflectionReader` seam) and the topics he holds
  strongest opinions on (read off the live :class:`PersonalityState` soul's taste
  axes, by conviction * liking strength). Nothing here is random.

* :class:`StoreFascinationReader` realises the reply/proactive compose's
  current-fascination read seam: it loads the persisted
  :class:`~bob.personality.fascination.Fascination` from the
  :class:`~bob.personality.ports.FascinationStore`, **ages** it against the injected
  :class:`~bob.kernel.ports.Clock`, and returns it only while it is still alive —
  a faded passion reads as ``None`` so the surface path no-ops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.application.usecases.handle_message import PersonalityState
    from bob.kernel.ports import Clock
    from bob.personality.fascination import Fascination
    from bob.personality.ports import FascinationStore, ReflectionReader

# A taste axis counts as a "strong opinion" — eligible grounding for a fascination —
# only when Bob both likes/dislikes it enough AND holds it with real conviction.
_STRONG_VALUE = 0.4
_STRONG_CONVICTION = 0.4


class RepoFascinationGrounding:
    """Bob's real grounding material: his latest reflection + strong taste topics."""

    def __init__(
        self,
        *,
        reflection: ReflectionReader,
        personality: PersonalityState,
    ) -> None:
        self._reflection = reflection
        self._personality = personality

    async def latest_reflection_text(self) -> str | None:
        """Return Bob's most recent real reflection text, or ``None`` if there is none."""
        return await self._reflection.latest_reflection_text()

    def strong_taste_topics(self) -> tuple[str, ...]:
        """Return the topics Bob holds strongest opinions on (strongest first).

        Reads the live soul's taste axes, keeps those past both the liking-strength
        and conviction floors, and orders them strongest-first by ``|value| *
        conviction`` — so a fascination pick is grounded in what Bob actually cares
        about, never an invented interest.
        """
        axes = self._personality.soul.taste.axes
        strong = [
            axis
            for axis in axes
            if abs(axis.value) >= _STRONG_VALUE and axis.conviction >= _STRONG_CONVICTION
        ]
        strong.sort(key=lambda axis: abs(axis.value) * axis.conviction, reverse=True)
        return tuple(axis.name for axis in strong)


class StoreFascinationReader:
    """Load + age Bob's current fascination; return it only while still alive."""

    def __init__(
        self,
        *,
        persona_id: str,
        store: FascinationStore,
        clock: Clock,
    ) -> None:
        self._persona_id = persona_id
        self._store = store
        self._clock = clock

    async def current_fascination(self) -> Fascination | None:
        """Return Bob's current, non-faded fascination, or ``None`` if there is none.

        Loads the persisted passion, ages it to "now" (intensity wanes), and drops it
        when it has faded past the floor — so a spent fascination never surfaces and
        the compose path no-ops until the evolution step grounds a fresh one.
        """
        stored = await self._store.load(self._persona_id)
        if stored is None:
            return None
        aged = stored.aged(now=self._clock.now())
        if aged.has_faded():
            return None
        return aged
