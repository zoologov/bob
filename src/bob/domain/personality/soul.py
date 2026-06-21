# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SOUL — the in-memory snapshot of Bob's persisted identity.

A pure, immutable value object assembled by callers from the on-disk soul
artifacts (``SoulStore`` reads ``SOUL.md`` + the JSON profiles; the domain never
touches the filesystem). It bundles Bob's identity narrative, current mood and
resting baseline, his taste engine, and his phantom preferences. The runtime
reads it on every turn to colour replies and score topics; :meth:`SOUL.with_mood`
yields an updated snapshot after a mood change without mutating the original.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from bob.domain.personality.taste import TasteEngine

if TYPE_CHECKING:
    from bob.domain.personality.mood import Mood, MoodDelta
    from bob.domain.personality.taste import TasteAxis


@dataclass(frozen=True, slots=True)
class SOUL:
    """An immutable snapshot of Bob's loaded soul (identity, mood, taste, phantoms).

    ``experience_count`` records how many self-evolution steps the soul has
    undergone — it is bumped by :meth:`with_taste`, so it grows monotonically as
    reflection reshapes Bob's tastes over time.
    """

    identity: str
    mood: Mood
    mood_baseline: Mood
    taste: TasteEngine
    phantom_prefs: tuple[str, ...] = field(default_factory=tuple)
    experience_count: int = 0

    def with_mood(self, mood: Mood) -> SOUL:
        """Return a copy of this soul carrying ``mood``, leaving the original intact."""
        return replace(self, mood=mood)

    def with_taste(self, axes: tuple[TasteAxis, ...]) -> SOUL:
        """Return a copy carrying a reinforced taste engine, experience bumped.

        The self-evolution analogue of :meth:`with_mood`: reflection produces an
        updated axis set, this swaps in a fresh :class:`TasteEngine` over those
        axes and increments ``experience_count``. The original is untouched.
        """
        return replace(
            self,
            taste=TasteEngine(axes=axes),
            experience_count=self.experience_count + 1,
        )

    def with_baseline(self, delta: MoodDelta) -> SOUL:
        """Return a copy whose resting baseline is nudged by ``delta`` (clamped).

        A small, durable shift of Bob's mood set-point — evolution may drift the
        baseline a touch alongside a taste change. Bounds are clamped by
        :meth:`Mood.update`. The original is untouched.
        """
        return replace(self, mood_baseline=self.mood_baseline.update(delta))
