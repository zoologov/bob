# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""SocialEnergy — Bob's reservoir for reaching out, as a pure [0, 1] value object.

The drive to speak draws on a finite reservoir: it **recovers** during silence,
is **spent** when Bob speaks proactively, and is **partially restored** when the
owner replies — yielding a natural cooldown without any timer or I/O. All
transitions are pure and the caller passes elapsed time (the clock lives in the
application layer), so the reservoir is fully deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

# The reservoir is bounded to the closed unit interval.
_MIN_LEVEL = 0.0
_MAX_LEVEL = 1.0

# Recovery rate per second of silence. At ~1/3600 the reservoir refills over
# roughly an hour of quiet — slow enough that proactivity stays occasional.
_RECOVERY_PER_SECOND = 1.0 / 3600.0

# A proactive message spends a fixed slice of the reservoir.
_SPEND_COST = 0.5

# An owner reply restores a fixed slice — a partial "you came back" bump.
_REPLY_RESTORE = 0.3


def _clamp(value: float) -> float:
    """Saturate ``value`` into the reservoir bounds rather than overflowing them."""
    return max(_MIN_LEVEL, min(_MAX_LEVEL, value))


@dataclass(frozen=True, slots=True)
class SocialEnergy:
    """Bob's bounded [0, 1] reservoir of drive-to-reach-out."""

    level: float

    def __post_init__(self) -> None:
        if not _MIN_LEVEL <= self.level <= _MAX_LEVEL:
            raise ValueError(
                f"social energy must be within [{_MIN_LEVEL}, {_MAX_LEVEL}], got {self.level}"
            )

    def recover(self, *, elapsed_seconds: float) -> SocialEnergy:
        """Return the reservoir replenished by ``elapsed_seconds`` of silence.

        Recovery is linear in elapsed time and saturates at the cap; a longer
        silence never recovers less than a shorter one.
        """
        if elapsed_seconds < 0.0:
            raise ValueError(f"elapsed seconds must be non-negative, got {elapsed_seconds}")
        return SocialEnergy(_clamp(self.level + elapsed_seconds * _RECOVERY_PER_SECOND))

    def spend(self) -> SocialEnergy:
        """Return the reservoir after Bob speaks once (drained, never below zero)."""
        return SocialEnergy(_clamp(self.level - _SPEND_COST))

    def replenish_from_reply(self) -> SocialEnergy:
        """Return the reservoir partially restored by an owner reply (capped at full)."""
        return SocialEnergy(_clamp(self.level + _REPLY_RESTORE))
