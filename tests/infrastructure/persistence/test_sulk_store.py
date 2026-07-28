# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteSulkStore — the per-persona обида state adapter (BOB-014 .2b).

Round-trips the domain :class:`SulkState` (active / intensity / low_streak / since /
announced) into a per-``persona_id`` SQLite row: the not-sulking default for an unseen
persona, the save→load round-trip (including the ``None`` ``since`` of a fresh state),
that a later save UPDATES the row (обида evolves — entered, decays, exits), per-persona
isolation (Bobiverse replicas), and survival across a restart. Carries NO memory and
NO soul — only the affect state (anti-Exodus).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.social.adapters.sulk_store import SqliteSulkStore
from bob.social.sulk import SulkState

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OTHER_PERSONA = "bill"
_SINCE = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_fresh_default_for_unseen_persona(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteSulkStore(repo)

    # An unseen persona has never been hurt — the not-sulking default.
    assert await store.load(_PERSONA) == SulkState()


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteSulkStore(repo)
    state = SulkState(
        active=True, intensity=0.8, low_streak=3, since=_SINCE, announced=True
    )

    await store.save(_PERSONA, state)
    loaded = await store.load(_PERSONA)

    assert loaded == state


async def test_save_preserves_none_since(repo: SqliteMemoryRepo) -> None:
    store = SqliteSulkStore(repo)
    fresh = SulkState(low_streak=2)

    await store.save(_PERSONA, fresh)

    assert await store.load(_PERSONA) == fresh


async def test_save_updates_an_evolving_sulk(repo: SqliteMemoryRepo) -> None:
    store = SqliteSulkStore(repo)
    await store.save(_PERSONA, SulkState(active=True, intensity=1.0, since=_SINCE))

    # обида decays — a later save overwrites the row with the newer state.
    decayed = SulkState(active=True, intensity=0.3, since=_SINCE, announced=True)
    await store.save(_PERSONA, decayed)

    assert await store.load(_PERSONA) == decayed


async def test_state_is_isolated_per_persona(repo: SqliteMemoryRepo) -> None:
    store = SqliteSulkStore(repo)
    hurt = SulkState(active=True, intensity=0.5, since=_SINCE)

    await store.save(_PERSONA, hurt)

    assert await store.load(_PERSONA) == hurt
    assert await store.load(_OTHER_PERSONA) == SulkState()


async def test_state_survives_a_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    state = SulkState(active=True, intensity=0.6, low_streak=4, since=_SINCE, announced=True)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteSulkStore(first).save(_PERSONA, state)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteSulkStore(second).load(_PERSONA)
    await second.close()

    assert loaded == state
