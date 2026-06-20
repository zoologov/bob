# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RecordOwnerActivity — fold an owner message into proactivity state.

When the owner writes (the reactive ``HandleMessage`` path), proactivity must
notice: :class:`RecordOwnerActivity` stamps ``last_user_msg_at`` to the injected
``now`` and partially restores the :class:`SocialEnergy` reservoir (a "you came
back" bump), preserving the rest of the per-persona state. That keeps the engine's
owner-cooldown and energy reflecting real interaction. These tests pin the
transition on a fake store and a fixed clock — pure, deterministic, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.application.proactivity.record_owner_activity import RecordOwnerActivity
from bob.domain.proactivity.social_energy import SocialEnergy
from bob.domain.proactivity.state import ProactivityState

_PERSONA = "bob"
_NOW = datetime(2026, 6, 20, 20, 0, tzinfo=UTC)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _FakeStore:
    def __init__(self, state: ProactivityState) -> None:
        self._state = state
        self.saved: ProactivityState | None = None

    async def load(self, persona_id: str) -> ProactivityState:  # noqa: ARG002
        return self._state

    async def save(self, persona_id: str, state: ProactivityState) -> None:  # noqa: ARG002
        self.saved = state
        self._state = state


def _state(*, energy: float = 0.2, enabled: bool = True) -> ProactivityState:
    return ProactivityState(
        social_energy=SocialEnergy(energy),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=enabled,
    )


@pytest.mark.asyncio
async def test_records_marker_and_restores_energy() -> None:
    store = _FakeStore(_state(energy=0.2))
    recorder = RecordOwnerActivity(
        store=store, clock=_FixedClock(_NOW), persona_id=_PERSONA
    )

    await recorder.run()

    assert store.saved is not None
    assert store.saved.last_user_msg_at == _NOW
    # Energy is partially restored (the "you came back" bump), not reset.
    assert store.saved.social_energy.level > 0.2


@pytest.mark.asyncio
async def test_preserves_enabled_flag_and_last_spoke() -> None:
    store = _FakeStore(_state(energy=0.5, enabled=False))
    recorder = RecordOwnerActivity(
        store=store, clock=_FixedClock(_NOW), persona_id=_PERSONA
    )

    await recorder.run()

    assert store.saved is not None
    # The owner's /quiet mute must survive an incoming message.
    assert store.saved.proactivity_enabled is False
    assert store.saved.last_spoke_at is None


@pytest.mark.asyncio
async def test_energy_restore_saturates_at_full() -> None:
    store = _FakeStore(_state(energy=0.95))
    recorder = RecordOwnerActivity(
        store=store, clock=_FixedClock(_NOW), persona_id=_PERSONA
    )

    await recorder.run()

    assert store.saved is not None
    assert store.saved.social_energy.level <= 1.0
