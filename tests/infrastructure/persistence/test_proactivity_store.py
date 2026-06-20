# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteProactivityStore — the per-persona proactivity state adapter.

The store round-trips the domain :class:`ProactivityState` (energy reservoir,
last-spoke / last-user markers, and the owner-mute flag) into a per-``persona_id``
SQLite row, plus an infrastructure-level ``mute_until`` timed-mute expiry. These
tests cover the default for an unseen persona, the save→load round-trip (including
``None`` markers), per-persona isolation (Bobiverse replicas), the timed-mute
expiry, and restart survival.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.proactivity.social_energy import SocialEnergy
from bob.domain.proactivity.state import ProactivityState
from bob.infrastructure.persistence.proactivity_store import SqliteProactivityStore
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OTHER_PERSONA = "bill"
_SPOKE_AT = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
_USER_AT = datetime(2026, 6, 20, 9, 30, tzinfo=UTC)
_MUTE_UNTIL = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_default_for_unseen_persona(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)

    state = await store.load(_PERSONA)

    assert state.social_energy == SocialEnergy(0.0)
    assert state.last_spoke_at is None
    assert state.last_user_msg_at is None
    assert state.proactivity_enabled is True


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)
    state = ProactivityState(
        social_energy=SocialEnergy(0.7),
        last_spoke_at=_SPOKE_AT,
        last_user_msg_at=_USER_AT,
        proactivity_enabled=False,
    )

    await store.save(_PERSONA, state)
    loaded = await store.load(_PERSONA)

    assert loaded.social_energy == SocialEnergy(0.7)
    assert loaded.last_spoke_at == _SPOKE_AT
    assert loaded.last_user_msg_at == _USER_AT
    assert loaded.proactivity_enabled is False


async def test_save_preserves_none_markers(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)
    state = ProactivityState(
        social_energy=SocialEnergy(0.2),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=True,
    )

    await store.save(_PERSONA, state)
    loaded = await store.load(_PERSONA)

    assert loaded.last_spoke_at is None
    assert loaded.last_user_msg_at is None


async def test_save_replaces_prior_state(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)
    await store.save(
        _PERSONA,
        ProactivityState(
            social_energy=SocialEnergy(0.1),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=True,
        ),
    )

    await store.save(
        _PERSONA,
        ProactivityState(
            social_energy=SocialEnergy(0.9),
            last_spoke_at=_SPOKE_AT,
            last_user_msg_at=None,
            proactivity_enabled=False,
        ),
    )
    loaded = await store.load(_PERSONA)

    assert loaded.social_energy == SocialEnergy(0.9)
    assert loaded.proactivity_enabled is False


async def test_state_is_isolated_per_persona(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)
    await store.save(
        _PERSONA,
        ProactivityState(
            social_energy=SocialEnergy(0.8),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=False,
        ),
    )

    other = await store.load(_OTHER_PERSONA)

    assert other.social_energy == SocialEnergy(0.0)
    assert other.proactivity_enabled is True


# --- Timed mute (infrastructure-level expiry) ---------------------------------


async def test_mute_until_defaults_to_none(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)

    assert await store.get_mute_until(_PERSONA) is None


async def test_set_mute_until_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)

    await store.set_mute_until(_PERSONA, _MUTE_UNTIL)

    assert await store.get_mute_until(_PERSONA) == _MUTE_UNTIL


async def test_set_mute_until_none_clears_it(repo: SqliteMemoryRepo) -> None:
    store = SqliteProactivityStore(repo)
    await store.set_mute_until(_PERSONA, _MUTE_UNTIL)

    await store.set_mute_until(_PERSONA, None)

    assert await store.get_mute_until(_PERSONA) is None


async def test_mute_until_survives_state_save(repo: SqliteMemoryRepo) -> None:
    """Saving the domain state must not wipe the infra-level timed-mute expiry."""
    store = SqliteProactivityStore(repo)
    await store.set_mute_until(_PERSONA, _MUTE_UNTIL)

    await store.save(
        _PERSONA,
        ProactivityState(
            social_energy=SocialEnergy(0.5),
            last_spoke_at=None,
            last_user_msg_at=None,
            proactivity_enabled=False,
        ),
    )

    assert await store.get_mute_until(_PERSONA) == _MUTE_UNTIL


# --- Restart survival ---------------------------------------------------------


async def test_state_survives_a_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "bob.db"
    first = SqliteMemoryRepo(db_path)
    await first.initialize()
    await SqliteProactivityStore(first).save(
        _PERSONA,
        ProactivityState(
            social_energy=SocialEnergy(0.6),
            last_spoke_at=_SPOKE_AT,
            last_user_msg_at=_USER_AT,
            proactivity_enabled=False,
        ),
    )
    await SqliteProactivityStore(first).set_mute_until(_PERSONA, _MUTE_UNTIL)
    await first.close()

    second = SqliteMemoryRepo(db_path)
    await second.initialize()
    try:
        store = SqliteProactivityStore(second)
        loaded = await store.load(_PERSONA)
        assert loaded.social_energy == SocialEnergy(0.6)
        assert loaded.last_spoke_at == _SPOKE_AT
        assert loaded.proactivity_enabled is False
        assert await store.get_mute_until(_PERSONA) == _MUTE_UNTIL
    finally:
        await second.close()
