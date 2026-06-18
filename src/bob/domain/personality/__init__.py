# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Personality domain — Bob's Higher Mind as pure, deterministic logic.

No I/O lives here: no LLM, no Telegram, no SQLite, no clock. These are value
objects and domain services (:class:`Mood`, :class:`TasteEngine`,
:class:`Negotiation`, :class:`SOUL`) that the application layer orchestrates and
the persistence adapter maps to and from disk artifacts. Scoring and tone are
deterministic so they are unit-testable without any model.
"""

from __future__ import annotations

from bob.domain.personality.mood import Mood, MoodDelta
from bob.domain.personality.negotiation import (
    Negotiation,
    NegotiationZone,
    Stance,
)
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine, Verdict

__all__ = [
    "SOUL",
    "Mood",
    "MoodDelta",
    "Negotiation",
    "NegotiationZone",
    "Stance",
    "TasteAxis",
    "TasteEngine",
    "Verdict",
]
