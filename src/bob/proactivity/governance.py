# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Governance — pure ceilings that *veto* a proactive message (no I/O, no clock).

The urge model is the engine; governance is the brake. Given the current local
time and a snapshot of recent history, :meth:`Governance.allows` answers a single
boolean — may Bob speak proactively right now? — by applying six vetoes:

* **quiet-hours** — a hard floor on the local clock (default 23:00 to 09:00),
* **owner-mute** — a persisted flag the owner toggles via ``/quiet`` / ``/wake``,
* **anti-spam** — a per-window ceiling on proactive messages,
* **min-gap** — a minimum interval between two proactive messages,
* **owner-cooldown** — a quiet interval after the owner's own last message, and
* **sulk** — a ceiling while Bob is обижен (BOB-014 .2b): he does not write first
  while hurt; it lifts on its own as обида recovers (guaranteed exit).

These are ceilings only: governance never *raises* the urge, it only blocks. The
"now" is injected by the caller (clock lives in the application layer), so the
policy is pure and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

# Default quiet-hours window on the local clock. Both boundaries are inclusive of
# the awake side: 23:00 is already quiet; 09:00 is awake again.
_DEFAULT_QUIET_START_HOUR = 23
_DEFAULT_QUIET_END_HOUR = 9

# A small per-day ceiling on proactive messages keeps Bob from chattering.
_DEFAULT_MAX_PER_WINDOW = 4

# Sane spacing defaults: no two proactive messages closer than the min-gap, and a
# brief pause after the owner writes so Bob never talks over them.
_DEFAULT_MIN_GAP = timedelta(hours=1)
_DEFAULT_OWNER_COOLDOWN = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class GovernanceConfig:
    """Tunable veto thresholds for :class:`Governance` (all named, all defaulted)."""

    quiet_start_hour: int = _DEFAULT_QUIET_START_HOUR
    quiet_end_hour: int = _DEFAULT_QUIET_END_HOUR
    max_per_window: int = _DEFAULT_MAX_PER_WINDOW
    min_gap: timedelta = _DEFAULT_MIN_GAP
    owner_cooldown: timedelta = _DEFAULT_OWNER_COOLDOWN


@dataclass(frozen=True, slots=True)
class ProactiveHistory:
    """The recent-activity snapshot governance reasons over (caller-supplied).

    ``sulk_active`` (BOB-014 .2b) is the обида ceiling: while Bob is hurt он не пишет
    первым. It defaults to ``False`` so a caller that does not model обида (or a Bob
    who is not hurt) behaves exactly as before — the veto only ever blocks.
    """

    last_spoke_at: datetime | None
    last_user_msg_at: datetime | None
    sent_in_window: int
    muted: bool
    sulk_active: bool = False


def _in_quiet_hours(now: datetime, *, start_hour: int, end_hour: int) -> bool:
    """Whether the local ``now`` falls inside the [start, end) quiet window.

    The window wraps midnight (e.g. 23:00→09:00): quiet runs from ``start_hour``
    inclusive up to ``end_hour`` exclusive, so 23:00 is quiet and 09:00 is awake.
    """
    current = now.timetz().replace(tzinfo=None)
    start = time(hour=start_hour)
    end = time(hour=end_hour)
    if start <= end:
        return start <= current < end
    # Wrapping window: quiet if at/after the start OR before the end.
    return current >= start or current < end


@dataclass(frozen=True, slots=True)
class Governance:
    """The proactivity veto policy — pure ceilings over time and history."""

    config: GovernanceConfig = GovernanceConfig()

    def allows(self, *, now: datetime, history: ProactiveHistory) -> bool:
        """Return whether a proactive message is permitted at ``now``.

        ``True`` only when every veto clears: not muted, not обижен (sulk), outside
        quiet hours, below the per-window ceiling, past the min-gap since Bob last
        spoke, and past the cooldown since the owner's last message.
        """
        vetoes = (
            history.muted,
            # BOB-014 .2b: обида suppresses the reach-out — Bob doesn't write first
            # while hurt. It lifts on its own as обида recovers (guaranteed exit).
            history.sulk_active,
            _in_quiet_hours(
                now,
                start_hour=self.config.quiet_start_hour,
                end_hour=self.config.quiet_end_hour,
            ),
            history.sent_in_window >= self.config.max_per_window,
            self._within(now, history.last_spoke_at, self.config.min_gap),
            self._within(now, history.last_user_msg_at, self.config.owner_cooldown),
        )
        return not any(vetoes)

    @staticmethod
    def _within(now: datetime, marker: datetime | None, window: timedelta) -> bool:
        """Whether ``marker`` is set and lies within ``window`` before ``now``."""
        if marker is None:
            return False
        return now - marker < window
