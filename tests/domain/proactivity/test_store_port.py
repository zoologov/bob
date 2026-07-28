# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ProactivityStore port — a structural protocol the engine depends on."""

from __future__ import annotations

from datetime import UTC, datetime

from bob.proactivity.ports import ProactivityStore
from bob.proactivity.social_energy import SocialEnergy
from bob.proactivity.state import ProactivityState


class _InMemoryStore:
    """A minimal in-memory adapter proving the protocol is satisfiable."""

    def __init__(self, state: ProactivityState) -> None:
        self._state = state

    async def load(self, persona_id: str) -> ProactivityState:  # noqa: ARG002
        return self._state

    async def save(self, persona_id: str, state: ProactivityState) -> None:  # noqa: ARG002
        self._state = state


def test_in_memory_store_satisfies_protocol() -> None:
    # Arrange
    state = ProactivityState(
        social_energy=SocialEnergy(0.5),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=True,
    )

    # Act
    store: ProactivityStore = _InMemoryStore(state)

    # Assert: an object with load/save is structurally a ProactivityStore.
    assert isinstance(store, ProactivityStore)


def test_proactivity_state_carries_persisted_fields() -> None:
    # Arrange / Act
    now = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    state = ProactivityState(
        social_energy=SocialEnergy(0.7),
        last_spoke_at=now,
        last_user_msg_at=now,
        proactivity_enabled=False,
    )

    # Assert: the per-persona engine state the store round-trips.
    assert state.social_energy.level == 0.7
    assert state.last_spoke_at == now
    assert state.proactivity_enabled is False
