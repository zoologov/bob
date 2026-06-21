# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Taste self-evolution — the pure kernel that reflection feeds into the soul.

A single reflection nudges one taste axis. The update is deliberately *slow* and
*self-damping*: both the liking shift and the conviction growth are scaled by
``(1 - conviction)``, so a settled opinion barely moves while an untested one
adapts. This ``(1 - conviction)`` factor is THE anti-runaway guardrail — without
it the personality would drift unbounded over many reflections.

Pure and deterministic: no I/O, no LLM, no clock. Bounds are clamped hard so the
result is always a valid :class:`TasteAxis` (value in ``[-1, 1]``, conviction in
``[0, 1]``). The application layer decides *which* axis and *what* nudge; this
module only computes the next axis.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.personality.taste import TasteAxis

# Liking value is bounded to [-1, 1]; conviction to [0, 1].
_MIN_VALUE = -1.0
_MAX_VALUE = 1.0
_MIN_CONVICTION = 0.0
_MAX_CONVICTION = 1.0

# Default learning rates — small, so evolution plays out over many reflections.
# ALPHA scales the liking shift; BETA the conviction growth. Both are damped by
# (1 - conviction). Overridable via personality.evolution.{alpha,beta} in config.
ALPHA = 0.15
BETA = 0.10


def _clamp(value: float, low: float, high: float) -> float:
    """Saturate ``value`` into ``[low, high]`` rather than overflowing it."""
    return max(low, min(high, value))


def reinforce(
    axis: TasteAxis,
    *,
    nudge: float,
    alpha: float = ALPHA,
    beta: float = BETA,
) -> TasteAxis:
    """Return ``axis`` nudged by a signed ``nudge`` (anti-runaway, clamped).

    ``value' = clamp(value + alpha * nudge * (1 - conviction), -1, 1)`` — a firm
    opinion (high conviction) shifts strictly less than a weak one for the same
    nudge. ``conviction' = clamp(conviction + beta * |nudge| * (1 - conviction),
    0, 1)`` — conviction firms asymptotically toward 1 (damped growth, no
    overshoot). ``name`` and ``experience_count`` are preserved.
    """
    damping = 1.0 - axis.conviction
    new_value = _clamp(axis.value + alpha * nudge * damping, _MIN_VALUE, _MAX_VALUE)
    new_conviction = _clamp(
        axis.conviction + beta * abs(nudge) * damping,
        _MIN_CONVICTION,
        _MAX_CONVICTION,
    )
    return replace(axis, value=new_value, conviction=new_conviction)
