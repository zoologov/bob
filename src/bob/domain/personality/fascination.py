# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Fascination — the topic Bob is *into* right now, ageing and decaying (BOB-020).

A pure, immutable value object: Bob's current passion is a ``topic`` he derived
from his real inner life (a recent reflection or a strong taste — never random),
an ``intensity`` in ``[0, 1]`` measuring how alive it is for him, and the
``created_at`` instant it took hold. It is a *state*, not a rule — the runtime
surfaces it rarely, à propos, and it evolves slowly over time.

Ageing is the decay law: intensity wanes with age via a smooth exponential
half-life, bounded into ``[MIN_INTENSITY, MAX_INTENSITY]`` so it never runs away
or flips sign. :meth:`Fascination.aged` returns the same passion seen "now" (topic
and origin untouched, only intensity faded); once it sinks at or below
:data:`DECAY_FLOOR` it :meth:`has_faded` — the signal the evolution step reads to
replace a spent fascination with a fresh, freshly-grounded one. No I/O, no clock
of its own (``now`` is passed in), so it stays trivially testable and pure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

# Intensity is a bounded scalar in [0, 1]: 0 is spent, 1 is a brand-new passion.
MIN_INTENSITY = 0.0
MAX_INTENSITY = 1.0

# Below (or at) this aged intensity a fascination is "spent" — has_faded() is true,
# so the evolution step retires it for a fresh, freshly-grounded one.
DECAY_FLOOR = 0.15

# Exponential decay half-life: a fascination loses half its intensity over this
# many hours of age. Slow by design — a passion is meant to last days, not minutes,
# so it reads as a real evolving interest, not a flicker.
_HALF_LIFE_HOURS = 72.0

_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class Fascination:
    """Bob's current passion: a grounded topic, its intensity, and when it took hold."""

    topic: str
    intensity: float
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("fascination topic must be non-empty")
        if not MIN_INTENSITY <= self.intensity <= MAX_INTENSITY:
            raise ValueError(
                f"fascination intensity must be within "
                f"[{MIN_INTENSITY}, {MAX_INTENSITY}], got {self.intensity}"
            )

    def aged(self, *, now: datetime) -> Fascination:
        """Return this passion seen at ``now`` — same topic/origin, intensity faded.

        Intensity decays exponentially with age (half-life :data:`_HALF_LIFE_HOURS`)
        and is clamped into ``[MIN_INTENSITY, MAX_INTENSITY]``, so the result never
        runs away or goes negative. A ``now`` at or before ``created_at`` leaves
        intensity unchanged (no negative-age boost). The topic and ``created_at`` are
        preserved — only intensity moves — so the passion's identity is stable.
        """
        age_hours = max(0.0, (now - self.created_at).total_seconds() / _SECONDS_PER_HOUR)
        decay = 0.5 ** (age_hours / _HALF_LIFE_HOURS)
        faded = _clamp(self.intensity * decay)
        if faded == self.intensity:
            return self
        return Fascination(topic=self.topic, intensity=faded, created_at=self.created_at)

    def has_faded(self) -> bool:
        """Whether this passion has decayed to spent (intensity at/under the floor)."""
        return self.intensity <= DECAY_FLOOR


def _clamp(value: float) -> float:
    """Clamp an intensity into the bounded ``[MIN_INTENSITY, MAX_INTENSITY]`` range."""
    if math.isnan(value):
        return MIN_INTENSITY
    return max(MIN_INTENSITY, min(MAX_INTENSITY, value))
