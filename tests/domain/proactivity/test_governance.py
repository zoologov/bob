# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Governance — pure quiet-hours / anti-spam / gap / cooldown / mute vetoes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.domain.proactivity.governance import Governance, GovernanceConfig, ProactiveHistory

# A waking-hours reference "now": 14:00 local, well clear of quiet hours.
_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)


def _history(
    *,
    last_spoke_at: datetime | None = None,
    last_user_msg_at: datetime | None = None,
    sent_in_window: int = 0,
    muted: bool = False,
) -> ProactiveHistory:
    return ProactiveHistory(
        last_spoke_at=last_spoke_at,
        last_user_msg_at=last_user_msg_at,
        sent_in_window=sent_in_window,
        muted=muted,
    )


def test_allows_when_clear() -> None:
    # Arrange: waking hours, no recent activity, not muted.
    governance = Governance()

    # Act
    allowed = governance.allows(now=_NOW, history=_history())

    # Assert
    assert allowed is True


def test_quiet_hours_hard_floor_blocks_at_night() -> None:
    # Arrange: 03:00 local is inside the default 23:00 to 09:00 quiet window.
    night = _NOW.replace(hour=3)

    # Act
    allowed = Governance().allows(now=night, history=_history())

    # Assert: a hard floor — nothing fires at night.
    assert allowed is False


def test_quiet_hours_boundary_open_at_nine() -> None:
    # Arrange: 09:00 is the inclusive end of quiet — Bob may speak again.
    wake = _NOW.replace(hour=9, minute=0)

    # Act
    allowed = Governance().allows(now=wake, history=_history())

    # Assert
    assert allowed is True


def test_quiet_hours_boundary_closed_at_eleven_pm() -> None:
    # Arrange: 23:00 is the inclusive start of quiet.
    sleep = _NOW.replace(hour=23, minute=0)

    # Act
    allowed = Governance().allows(now=sleep, history=_history())

    # Assert
    assert allowed is False


def test_min_gap_blocks_back_to_back() -> None:
    # Arrange: Bob spoke a minute ago — under the min-gap.
    config = GovernanceConfig(min_gap=timedelta(minutes=30))
    governance = Governance(config=config)
    recent = _history(last_spoke_at=_NOW - timedelta(minutes=1))

    # Act
    allowed = governance.allows(now=_NOW, history=recent)

    # Assert
    assert allowed is False


def test_min_gap_allows_after_gap_elapses() -> None:
    # Arrange: the last proactive message is well past the min-gap.
    config = GovernanceConfig(min_gap=timedelta(minutes=30))
    governance = Governance(config=config)
    old = _history(last_spoke_at=_NOW - timedelta(hours=2))

    # Act
    allowed = governance.allows(now=_NOW, history=old)

    # Assert
    assert allowed is True


def test_cooldown_after_owner_message_blocks() -> None:
    # Arrange: the owner just wrote — don't pounce on top of them.
    config = GovernanceConfig(owner_cooldown=timedelta(minutes=10))
    governance = Governance(config=config)
    recent = _history(last_user_msg_at=_NOW - timedelta(minutes=2))

    # Act
    allowed = governance.allows(now=_NOW, history=recent)

    # Assert
    assert allowed is False


def test_cooldown_after_owner_message_clears() -> None:
    # Arrange: the owner's last message is past the cooldown.
    config = GovernanceConfig(owner_cooldown=timedelta(minutes=10))
    governance = Governance(config=config)
    old = _history(last_user_msg_at=_NOW - timedelta(hours=1))

    # Act
    allowed = governance.allows(now=_NOW, history=old)

    # Assert
    assert allowed is True


def test_anti_spam_window_blocks_at_max() -> None:
    # Arrange: already at the per-window ceiling.
    config = GovernanceConfig(max_per_window=3)
    governance = Governance(config=config)
    saturated = _history(sent_in_window=3)

    # Act
    allowed = governance.allows(now=_NOW, history=saturated)

    # Assert
    assert allowed is False


def test_anti_spam_window_allows_below_max() -> None:
    # Arrange: under the per-window ceiling.
    config = GovernanceConfig(max_per_window=3)
    governance = Governance(config=config)
    below = _history(sent_in_window=2)

    # Act
    allowed = governance.allows(now=_NOW, history=below)

    # Assert
    assert allowed is True


def test_owner_mute_blocks_everything() -> None:
    # Arrange: owner muted proactivity — overrides all else.
    muted = _history(muted=True)

    # Act
    allowed = Governance().allows(now=_NOW, history=muted)

    # Assert
    assert allowed is False


def test_governance_is_deterministic() -> None:
    # Arrange
    governance = Governance()
    history = _history(last_spoke_at=_NOW - timedelta(hours=3))

    # Act / Assert
    assert governance.allows(now=_NOW, history=history) == governance.allows(
        now=_NOW, history=history
    )
