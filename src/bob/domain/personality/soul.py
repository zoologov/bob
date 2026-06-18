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

if TYPE_CHECKING:
    from bob.domain.personality.mood import Mood
    from bob.domain.personality.taste import TasteEngine


@dataclass(frozen=True, slots=True)
class SOUL:
    """An immutable snapshot of Bob's loaded soul (identity, mood, taste, phantoms)."""

    identity: str
    mood: Mood
    mood_baseline: Mood
    taste: TasteEngine
    phantom_prefs: tuple[str, ...] = field(default_factory=tuple)

    def with_mood(self, mood: Mood) -> SOUL:
        """Return a copy of this soul carrying ``mood``, leaving the original intact."""
        return replace(self, mood=mood)
