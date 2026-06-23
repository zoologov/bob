# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteFascinationStore — the per-persona current-fascination adapter.

Round-trips the domain :class:`Fascination` (grounded topic, decaying intensity,
created-at instant) into a per-``persona_id`` SQLite row: the ``None`` default for
an unseen persona, the save→load round-trip, replacement of a prior fascination,
per-persona isolation (Bobiverse replicas), and survival across a restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.personality.fascination import Fascination
from bob.infrastructure.persistence.fascination_store import SqliteFascinationStore
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OTHER_PERSONA = "bill"
_CREATED = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_none_for_unseen_persona(repo: SqliteMemoryRepo) -> None:
    store = SqliteFascinationStore(repo)

    assert await store.load(_PERSONA) is None


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteFascinationStore(repo)
    fascination = Fascination(
        topic="орбитальная механика", intensity=0.82, created_at=_CREATED
    )

    await store.save(_PERSONA, fascination)
    loaded = await store.load(_PERSONA)

    assert loaded == fascination


async def test_save_replaces_prior_fascination(repo: SqliteMemoryRepo) -> None:
    store = SqliteFascinationStore(repo)
    await store.save(_PERSONA, Fascination(topic="old", intensity=0.4, created_at=_CREATED))
    fresh = Fascination(topic="new", intensity=0.9, created_at=_CREATED)

    await store.save(_PERSONA, fresh)

    assert await store.load(_PERSONA) == fresh


async def test_is_per_persona_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteFascinationStore(repo)
    bob_f = Fascination(topic="звёзды", intensity=0.7, created_at=_CREATED)

    await store.save(_PERSONA, bob_f)

    assert await store.load(_PERSONA) == bob_f
    assert await store.load(_OTHER_PERSONA) is None


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    fascination = Fascination(topic="фуги Баха", intensity=0.6, created_at=_CREATED)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteFascinationStore(first).save(_PERSONA, fascination)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteFascinationStore(second).load(_PERSONA)
    await second.close()

    assert loaded == fascination
