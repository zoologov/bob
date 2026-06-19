# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""TasteEngine — deterministic verdicts over Bob's taste axes (no LLM, no I/O).

Each :class:`TasteAxis` records how much Bob likes a topic (``value`` in
``[-1, 1]``), how firmly he holds that opinion (``conviction`` in ``[0, 1]``),
and how many times he has experienced it (``experience_count``). Scoring is
*deterministic*: an object/topic maps to a :class:`Verdict`
(love/like/neutral/dislike/hate) purely from value and conviction — the LLM only
*verbalises* the verdict elsewhere, it never decides it. Conviction gates the
extremes: a strong-but-untested liking reaches only ``LIKE``, not ``LOVE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Liking value is bounded to [-1, 1]; conviction to [0, 1].
_MIN_VALUE = -1.0
_MAX_VALUE = 1.0
_MIN_CONVICTION = 0.0
_MAX_CONVICTION = 1.0

# A topic is an opinion (not neutral) only past this absolute liking value.
_OPINION_THRESHOLD = 0.2

# Reaching an extreme verdict (love/hate) needs both a strong value and enough
# conviction to back it; otherwise the verdict softens one step inward.
_EXTREME_VALUE_THRESHOLD = 0.7
_EXTREME_CONVICTION_THRESHOLD = 0.5


class Verdict(Enum):
    """How Bob feels about a scored object/topic, strongest to weakest."""

    LOVE = "love"
    LIKE = "like"
    NEUTRAL = "neutral"
    DISLIKE = "dislike"
    HATE = "hate"


@dataclass(frozen=True, slots=True)
class TasteAxis:
    """One dimension of Bob's taste: a topic, his liking, and his conviction."""

    name: str
    value: float
    conviction: float
    experience_count: int = 0

    def __post_init__(self) -> None:
        if not _MIN_VALUE <= self.value <= _MAX_VALUE:
            raise ValueError(
                f"taste value must be within [{_MIN_VALUE}, {_MAX_VALUE}], got {self.value}"
            )
        if not _MIN_CONVICTION <= self.conviction <= _MAX_CONVICTION:
            raise ValueError(
                f"taste conviction must be within "
                f"[{_MIN_CONVICTION}, {_MAX_CONVICTION}], got {self.conviction}"
            )
        if self.experience_count < 0:
            raise ValueError(f"experience_count must be non-negative, got {self.experience_count}")


@dataclass(frozen=True, slots=True)
class TasteEngine:
    """Deterministic scorer mapping a topic to a :class:`Verdict` over taste axes."""

    axes: tuple[TasteAxis, ...] = field(default_factory=tuple)

    def score(self, topic: str) -> Verdict:
        """Return Bob's deterministic verdict on ``topic`` (NEUTRAL if unknown).

        Matching is case-insensitive. The sign of the axis value selects
        like/dislike; conviction gates whether a strong value escalates to the
        love/hate extreme.
        """
        axis = self._find(topic)
        if axis is None:
            return Verdict.NEUTRAL
        return self._verdict_for(axis)

    def _find(self, topic: str) -> TasteAxis | None:
        key = topic.strip().casefold()
        for axis in self.axes:
            if axis.name.casefold() == key:
                return axis
        return None

    @staticmethod
    def _verdict_for(axis: TasteAxis) -> Verdict:
        if abs(axis.value) < _OPINION_THRESHOLD:
            return Verdict.NEUTRAL
        extreme = (
            abs(axis.value) >= _EXTREME_VALUE_THRESHOLD
            and axis.conviction >= _EXTREME_CONVICTION_THRESHOLD
        )
        if axis.value > 0:
            return Verdict.LOVE if extreme else Verdict.LIKE
        return Verdict.HATE if extreme else Verdict.DISLIKE
