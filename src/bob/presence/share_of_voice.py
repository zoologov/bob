# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""ShareOfVoicePolicy — the soft ambient ceiling on how much airtime Bob takes.

Bob should feel like *one more participant*, not a bot that answers everything. The
policy turns his rolling :class:`~bob.presence.outgoing_activity.OutgoingActivity`
into a **damping multiplier** applied to the probability of barging into an ambient
(un-addressed) message: as his share of the room's airtime runs past a fair target
(``≈ 1 / (distinct_senders + 1)`` — as if he were just another person), the
multiplier shrinks, so he barges in less often. Two invariants are structural:

* **INV-1 (focus bypass):** a focused message (``focused=True`` — Bob was directly
  addressed) always returns ``1.0``. The ceiling NEVER throttles a direct address.
* **INV-3 (anti-script):** the multiplier is a soft, probabilistic scaler that never
  reaches zero (floored by ``share_min_multiplier``). Bob is dampened, never muted —
  a nudge, not a hard counter.

The verdict is a module-level pure function (:func:`share_damping`) — no I/O, clock
or rng — with :class:`ShareOfVoicePolicy` a thin config-carrying facade. The caller
multiplies its own barge probability by this factor and samples with its own
turn-local rng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.presence.rhythm_config import RhythmConfig

if TYPE_CHECKING:
    from bob.presence.outgoing_activity import OutgoingActivity

_FULL = 1.0


def fair_target_share(distinct_senders: int) -> float:
    """Bob's fair share of airtime — as if he were one more of the speakers."""
    return 1.0 / (distinct_senders + 1)


def share_damping(
    share: float,
    distinct_senders: int,
    *,
    focused: bool,
    min_multiplier: float,
    steepness: float,
) -> float:
    """Return the ``(0, 1]`` damping multiplier for a given share of voice.

    ``focused=True`` short-circuits to ``1.0`` (INV-1 — a direct address is never
    throttled). Otherwise, while ``share`` is at or under the fair target the
    multiplier is ``1.0``; past it, it decays smoothly with how far over Bob is,
    floored at ``min_multiplier > 0`` so he is dampened, not muted (INV-3).
    """
    if focused:
        return _FULL

    target = fair_target_share(distinct_senders)
    if share <= target:
        return _FULL

    # How far past the fair share Bob is, normalised into [0, 1].
    excess = (share - target) / (1.0 - target)
    decay = float((1.0 - excess) ** steepness)
    return min_multiplier + (_FULL - min_multiplier) * decay


@dataclass(frozen=True, slots=True)
class ShareOfVoicePolicy:
    """Config-carrying facade over :func:`share_damping` (the soft ambient ceiling)."""

    config: RhythmConfig = field(default_factory=RhythmConfig)

    def damping(self, activity: OutgoingActivity, *, focused: bool) -> float:
        """Return the ambient-barge damping multiplier for ``activity``.

        Delegates to :func:`share_damping` with this policy's tuned floor + steepness;
        ``focused`` bypasses the ceiling (INV-1).
        """
        return share_damping(
            activity.share,
            activity.distinct_senders,
            focused=focused,
            min_multiplier=self.config.share_min_multiplier,
            steepness=self.config.share_steepness,
        )
