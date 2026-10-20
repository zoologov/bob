# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Sulk — Bob's pure обида state (BOB-014 .2b).

Bob enters обида only when the OWNER relationship sits critically low for a
SUSTAINED run (not one bad message, not casual мат), is cold-but-still-Bob while
sulking, and is GUARANTEED to come out: intensity decays to zero by time alone
(warmth accelerates it), so there is never a permanent lock-out. Memory/soul are
never touched here — this is just an affect state. All transitions are pure and
deterministic (elapsed time + signals passed in).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.kernel.sulk import SulkState
from bob.social.sulk import SulkConfig, observe_relationship, recover

_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
# A warmth comfortably below the default critical threshold.
_LOW_WARMTH = -0.6
# A warmth comfortably above it (a healthy relationship).
_OK_WARMTH = 0.3


def test_fresh_state_is_not_sulking() -> None:
    # Arrange / Act
    state = SulkState()

    # Assert: a fresh Bob is not обижен, with no intensity and no streak.
    assert state.active is False
    assert state.intensity == 0.0
    assert state.low_streak == 0
    assert state.announced is False


def test_one_bad_message_does_not_enter_sulk() -> None:
    # Arrange: a single critically-low observation (one bad message).
    cfg = SulkConfig(sustain_count=3)

    # Act
    state = observe_relationship(
        SulkState(), person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: a single dip never enters обида — it needs sustaining.
    assert state.active is False
    assert state.low_streak == 1


def test_sustained_critical_drop_enters_sulk() -> None:
    # Arrange
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()

    # Act: three consecutive critically-low observations.
    for _ in range(3):
        state = observe_relationship(
            state, person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
        )

    # Assert: sustained → обида, with intensity and the entry stamp.
    assert state.active is True
    assert state.intensity > 0.0
    assert state.since == _NOW


def test_a_warm_message_resets_the_low_streak() -> None:
    # Arrange: two low observations build a streak.
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()
    for _ in range(2):
        state = observe_relationship(
            state, person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
        )

    # Act: a healthy turn breaks the run.
    state = observe_relationship(
        state, person_warmth=_OK_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: the streak resets, so обида never builds from intermittent dips.
    assert state.active is False
    assert state.low_streak == 0


def test_directed_hostility_drives_the_streak_even_when_warmth_ok() -> None:
    # Arrange: warmth is fine, but the turn carries DIRECTED hostility.
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()

    # Act
    for _ in range(3):
        state = observe_relationship(
            state, person_warmth=_OK_WARMTH, hostile=True, now=_NOW, config=cfg
        )

    # Assert: sustained directed hostility enters обида (it reacts to hostility,
    # not to a low number alone).
    assert state.active is True


def test_warmth_exactly_at_the_critical_threshold_counts_as_low() -> None:
    # The threshold is inclusive (``<=``): a warmth EXACTLY at critical is a low
    # observation, so a single such turn extends the streak (never one turn into обида).
    cfg = SulkConfig(critical_warmth=-0.4, sustain_count=3)

    state = observe_relationship(
        SulkState(), person_warmth=-0.4, hostile=False, now=_NOW, config=cfg
    )

    assert state.low_streak == 1
    assert state.active is False


def test_entry_sets_the_exact_streak_and_unannounced_flag() -> None:
    # On the entry transition the new state carries the EXACT sustaining streak and a
    # cleared announce flag (so GUPPI announces this fresh entry once, not zero/twice).
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()

    for _ in range(3):
        state = observe_relationship(
            state, person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
        )

    assert state.low_streak == 3
    assert state.announced is False


def test_active_observation_tracks_the_exact_streak() -> None:
    # While already обижен a further low turn keeps tracking the streak by exactly +1
    # (not reset, not dropped) — the streak stays meaningful across the обида.
    cfg = SulkConfig(sustain_count=1)
    state = observe_relationship(
        SulkState(), person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )
    assert state.low_streak == 1

    again = observe_relationship(
        state, person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    assert again.low_streak == 2


def test_observe_is_idempotent_once_sulking() -> None:
    # Arrange: already обижен.
    cfg = SulkConfig(sustain_count=1)
    state = observe_relationship(
        SulkState(), person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )
    assert state.active is True
    entered_at = state.since

    # Act: another low observation while already sulking.
    again = observe_relationship(
        state, person_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: it does not re-stamp the entry nor inflate past the cap — stable.
    assert again.active is True
    assert again.since == entered_at
    assert again.intensity <= 1.0


def test_recovery_decays_to_exit_by_time_alone() -> None:
    # Arrange: обижен with full intensity, NO warmth offered.
    cfg = SulkConfig(decay_per_second=0.001, exit_intensity=0.05)
    state = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)

    # Act: a very long quiet stretch with zero warmth.
    state = recover(state, elapsed_seconds=10_000.0, warmth_delta=0.0, config=cfg)

    # Assert: GUARANTEED exit — intensity decays to zero by time alone, so Bob
    # always отходит even if the owner never warms up. No permanent lock-out.
    assert state.active is False
    assert state.intensity == 0.0


def test_recovery_is_faster_with_warmth() -> None:
    # Arrange: identical обида state, recovered over the same short gap.
    cfg = SulkConfig(decay_per_second=0.0001, warmth_decay_bonus=0.5)
    base = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)

    # Act
    cold = recover(base, elapsed_seconds=100.0, warmth_delta=0.0, config=cfg)
    warm = recover(base, elapsed_seconds=100.0, warmth_delta=0.4, config=cfg)

    # Assert: тёплые сообщения accelerate the recovery (warm intensity is lower).
    assert warm.intensity < cold.intensity


def test_recovery_is_idempotent_when_not_sulking() -> None:
    # Arrange: not обижен.
    state = SulkState()

    # Act: a recovery tick on a non-sulking state.
    out = recover(state, elapsed_seconds=100.0, warmth_delta=0.0)

    # Assert: a no-op — recovery never "sticks" or reactivates обида.
    assert out.active is False
    assert out.intensity == 0.0


def test_zero_elapsed_is_allowed_and_decays_only_by_warmth() -> None:
    # The SulkTracker's "warm turn accelerates recovery" path calls recover with
    # elapsed_seconds == 0.0, so zero MUST be allowed (the guard is ``< 0``, not ``<= 0``)
    # and with zero warmth it is a pure no-op on intensity (time drove nothing).
    cfg = SulkConfig(warmth_decay_bonus=0.5)
    state = SulkState(active=True, intensity=0.8, since=_NOW, announced=True)

    unchanged = recover(state, elapsed_seconds=0.0, warmth_delta=0.0, config=cfg)
    warmed = recover(state, elapsed_seconds=0.0, warmth_delta=0.4, config=cfg)

    assert unchanged.intensity == 0.8  # zero elapsed + zero warmth → no decay
    assert warmed.intensity < 0.8  # a warm turn alone still pulls обида down


def test_default_warmth_delta_adds_no_recovery_bonus() -> None:
    # The recover() default warmth_delta is 0.0 (no implicit warmth): omitting it decays
    # by elapsed time ALONE, identical to passing an explicit zero.
    cfg = SulkConfig(decay_per_second=0.001, warmth_decay_bonus=0.5)
    state = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)

    implied = recover(state, elapsed_seconds=100.0, config=cfg)
    explicit = recover(state, elapsed_seconds=100.0, warmth_delta=0.0, config=cfg)

    assert implied == explicit


def test_positive_warmth_scales_the_bonus_up_not_down() -> None:
    # The warmth bonus MULTIPLIES the delta by warmth_decay_bonus (не делит): a larger
    # bonus yields MORE recovery, pinning the arithmetic direction.
    state = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)
    small = recover(
        state,
        elapsed_seconds=0.0,
        warmth_delta=0.4,
        config=SulkConfig(warmth_decay_bonus=0.2),
    )
    large = recover(
        state,
        elapsed_seconds=0.0,
        warmth_delta=0.4,
        config=SulkConfig(warmth_decay_bonus=0.9),
    )

    assert large.intensity < small.intensity


def test_exit_floors_streak_to_zero_exactly() -> None:
    # On the decay exit the state resets to a clean, reusable not-sulking row: intensity
    # zero AND low_streak exactly 0 (so a fresh later drop starts its streak from scratch).
    cfg = SulkConfig(decay_per_second=1.0, exit_intensity=0.05)
    state = SulkState(active=True, intensity=0.1, low_streak=5, since=_NOW, announced=True)

    out = recover(state, elapsed_seconds=1.0, warmth_delta=0.0, config=cfg)

    assert out.active is False
    assert out.low_streak == 0


def test_exit_boundary_is_inclusive_at_the_threshold() -> None:
    # The exit is inclusive (``<=``): intensity landing EXACTLY on exit_intensity ends
    # обида (Bob отходит at the floor, not one hair above it). Binary-exact fractions
    # (0.5 - 0.25 == 0.25) so the equality is not a floating-point near-miss.
    cfg = SulkConfig(decay_per_second=0.25, exit_intensity=0.25)
    state = SulkState(active=True, intensity=0.5, since=_NOW, announced=True)

    out = recover(state, elapsed_seconds=1.0, warmth_delta=0.0, config=cfg)

    assert out.active is False  # decayed to EXACTLY 0.25 → the inclusive floor exits


def test_recovery_clears_the_announced_flag_on_exit() -> None:
    # Arrange: обижен and already announced once.
    cfg = SulkConfig(decay_per_second=1.0, exit_intensity=0.05)
    state = SulkState(active=True, intensity=0.1, since=_NOW, announced=True)

    # Act: enough time to fall below the exit threshold.
    state = recover(state, elapsed_seconds=1.0, warmth_delta=0.0, config=cfg)

    # Assert: on exit the one-shot announce flag is cleared so the NEXT entry
    # announces afresh.
    assert state.active is False
    assert state.announced is False


def test_negative_elapsed_is_rejected() -> None:
    # Arrange / Act / Assert: time cannot run backwards.
    with pytest.raises(ValueError, match="non-negative"):
        recover(SulkState(active=True, intensity=0.5), elapsed_seconds=-1.0)
