# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""ReactionBudget — a separate, gentle budget for Bob's likes (pure policy).

A like is a cheap presence move, but a bot that likes *everything* reads as
scripted. This policy gates Bob's reactions on their own budget (independent of his
reply cadence): a like is admitted only when the message is genuinely notable
(``quality >= threshold``) AND enough time has passed since his last like
(``min_gap``) — so at most one reaction lands per short series, and Bob picks the
best message rather than reacting to each.

The verdict is a module-level pure function (:func:`reaction_allowed`) — ``now`` is
injected — with :class:`ReactionBudget` a thin config-carrying facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.presence.rhythm_config import RhythmConfig

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


def reaction_allowed(
    history: Sequence[datetime],
    *,
    quality: float,
    now: datetime,
    quality_threshold: float,
    min_gap_seconds: float,
) -> bool:
    """Return whether a like is in budget now (quality-gated + rate-limited).

    A like is allowed only when the message clears ``quality_threshold`` and the
    most-recent like in ``history`` is at least ``min_gap_seconds`` in the past — so
    one reaction lands per series, never a burst. An empty history admits a notable
    message immediately.
    """
    if quality < quality_threshold:
        return False
    if not history:
        return True
    most_recent = max(history)
    elapsed = (now - most_recent).total_seconds()
    return elapsed >= min_gap_seconds


@dataclass(frozen=True, slots=True)
class ReactionBudget:
    """Config-carrying facade over :func:`reaction_allowed` (the like budget)."""

    config: RhythmConfig = field(default_factory=RhythmConfig)

    def allows(
        self, history: Sequence[datetime], *, quality: float, now: datetime
    ) -> bool:
        """Return whether Bob may spend a like now, given his recent like history."""
        return reaction_allowed(
            history,
            quality=quality,
            now=now,
            quality_threshold=self.config.reaction_quality_threshold,
            min_gap_seconds=self.config.reaction_min_gap_seconds,
        )
