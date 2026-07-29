# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""NaturalDelayPolicy — the human floor under how fast Bob may reply (pure).

A real person does not answer a paragraph in 40 ms. The policy computes a **lower
bound** (seconds) on how long a turn should take before Bob's reply lands, from the
reply's length + complexity, relieved by urgency (a demanded, time-critical answer
comes quicker). It is only a FLOOR: the application waits ``max(floor, real
generation time)``, so genuine generation always wins when it is slower — the delay
never makes Bob *slower* than he really is, only stops him being inhumanly instant
(INV-9).

The verdict is a module-level pure function (:func:`delay_floor_seconds`) — the
clock lives in the application coordinator — with :class:`NaturalDelayPolicy` a thin
config-carrying facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bob.presence.rhythm_config import RhythmConfig


def clamp_unit(value: float) -> float:
    """Saturate ``value`` into the closed unit interval ``[0, 1]``."""
    return max(0.0, min(1.0, value))


def delay_floor_seconds(
    *,
    char_len: int,
    complexity: float,
    urgency: float,
    base_seconds: float,
    seconds_per_char: float,
    complexity_seconds: float,
    max_seconds: float,
    urgency_relief: float,
) -> float:
    """Return the ``>= 0`` second floor before a reply of this shape should land.

    Length and complexity lengthen the floor (reading + typing); urgency shortens it
    (a demanded answer comes faster). The raw floor is capped at ``max_seconds`` so a
    very long draft never floors an absurd wait, then relieved by urgency.
    """
    if char_len < 0:
        raise ValueError(f"char_len must be non-negative, got {char_len}")
    clamped_complexity = clamp_unit(complexity)
    clamped_urgency = clamp_unit(urgency)

    raw = (
        base_seconds
        + char_len * seconds_per_char
        + clamped_complexity * complexity_seconds
    )
    capped = min(raw, max_seconds)
    relief = 1.0 - clamped_urgency * urgency_relief
    return capped * relief


@dataclass(frozen=True, slots=True)
class NaturalDelayPolicy:
    """Config-carrying facade over :func:`delay_floor_seconds` (the human floor)."""

    config: RhythmConfig = field(default_factory=RhythmConfig)

    def floor_seconds(
        self, *, char_len: int, complexity: float, urgency: float
    ) -> float:
        """Return the human lower bound (seconds) for a reply of this shape."""
        cfg = self.config
        return delay_floor_seconds(
            char_len=char_len,
            complexity=complexity,
            urgency=urgency,
            base_seconds=cfg.delay_base_seconds,
            seconds_per_char=cfg.delay_seconds_per_char,
            complexity_seconds=cfg.delay_complexity_seconds,
            max_seconds=cfg.delay_max_seconds,
            urgency_relief=cfg.delay_urgency_relief,
        )
