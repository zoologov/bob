# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality
# beadloom:layer=domain

"""Personality state — the live, per-boot snapshot of Bob's soul (BOB-113 A).

:class:`PersonalityState` is the mutable holder every turn / tick reads and writes:
the reactive turn (``HandleMessage``), the heartbeat ticks, the proactivity engine and
the goal pursuit all share ONE instance. It lives with its only field's owner
(:class:`~bob.personality.soul.SOUL`), so its consumers import it downward from
``personality`` instead of reaching up into the application orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.personality.soul import SOUL

__all__ = ["PersonalityState"]


@dataclass
class PersonalityState:
    """Mutable in-memory holder for Bob's current soul snapshot across turns.

    The soul (identity, taste, phantoms) is constant for a boot; only the mood
    evolves, so each turn replaces the snapshot via :meth:`SOUL.with_mood`.
    """

    soul: SOUL
