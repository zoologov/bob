# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Relationship — Bob's per-person relationship quality (BOB-014): the shared VALUE.

A pure value object: how Bob stands with one person, on four axes each bounded to
``[-1, 1]`` (:data:`MIN_AXIS` .. :data:`MAX_AXIS`) and starting at ``0`` (neutral, a
person he has not formed a read on): **trust**, **respect**, **warmth**,
**compatibility**. Construction validates the bounds.

Why the shared kernel (BOB-113, RFC D): the relationship is read well below ``social``
in the runtime order — ``personality`` (reaction effect, voice tone) and
``conversation`` take it in their signatures — so declared in ``social`` it pulled
them into an upward edge. The BEHAVIOUR that accrues it stays in ``social``:
:func:`~bob.social.relationship.apply_interaction` (one turn's deltas + drift),
:func:`~bob.social.relationship.compromise_bias` and
:func:`~bob.social.relationship.endorsed_seed`. Value only here; no first-party import.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MAX_AXIS", "MIN_AXIS", "Relationship"]

# Each relationship axis is bounded to the closed interval [-1, 1].
MIN_AXIS = -1.0
MAX_AXIS = 1.0


@dataclass(frozen=True, slots=True)
class Relationship:
    """Bob's quality of relationship with one person, on four bounded axes."""

    sender_id: int
    trust: float = 0.0
    respect: float = 0.0
    warmth: float = 0.0
    compatibility: float = 0.0

    def __post_init__(self) -> None:
        for name in ("trust", "respect", "warmth", "compatibility"):
            value = getattr(self, name)
            if not MIN_AXIS <= value <= MAX_AXIS:
                raise ValueError(
                    f"relationship axis '{name}' must be within "
                    f"[{MIN_AXIS}, {MAX_AXIS}], got {value}"
                )
