# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqlitePersonSulkStore — the per-(persona, sender) обида adapter (BOB-066 2.5).

Round-trips the domain :class:`SulkState` into a per-``(persona_id, sender_id)`` SQLite
row: the not-sulking default for an unseen pair, the save→load round-trip, that a later
save UPSERTs, per-SENDER isolation (a sulk at one person leaves another untouched),
``active_sulks`` listing only the currently-обижен senders, and the idempotent one-time
backfill of the owner's legacy ``sulk_state`` row into ``person_sulk`` (byte-identical
upgrade). Carries NO memory and NO soul (anti-Exodus, a separate table).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.kernel.sulk import SulkState
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.adapters.person_sulk_store import SqlitePersonSulkStore
from bob.social.adapters.sulk_store import SqliteSulkStore

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OWNER = 111
_ALESHA = 222
_VLADIMIR = 333
_SINCE = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_fresh_default_for_unseen_pair(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqlitePersonSulkStore(repo)

    assert await store.load(_PERSONA, _ALESHA) == SulkState()


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)
    state = SulkState(
        active=True, intensity=0.8, low_streak=3, since=_SINCE, announced=True
    )

    await store.save(_PERSONA, _ALESHA, state)

    assert await store.load(_PERSONA, _ALESHA) == state


async def test_save_upserts_an_evolving_sulk(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)
    await store.save(_PERSONA, _ALESHA, SulkState(active=True, intensity=1.0, since=_SINCE))

    decayed = SulkState(active=True, intensity=0.3, since=_SINCE, announced=True)
    await store.save(_PERSONA, _ALESHA, decayed)

    assert await store.load(_PERSONA, _ALESHA) == decayed


async def test_state_is_isolated_per_sender(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)
    hurt = SulkState(active=True, intensity=0.5, since=_SINCE)

    await store.save(_PERSONA, _ALESHA, hurt)

    # Обида на Лёшу не задевает состояние по Владимиру.
    assert await store.load(_PERSONA, _ALESHA) == hurt
    assert await store.load(_PERSONA, _VLADIMIR) == SulkState()


async def test_active_sulks_lists_only_active_senders(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)
    await store.save(_PERSONA, _ALESHA, SulkState(active=True, intensity=0.7, since=_SINCE))
    await store.save(_PERSONA, _VLADIMIR, SulkState(active=False, intensity=0.0))

    assert await store.active_sulks(_PERSONA) == [_ALESHA]


async def test_active_sulks_is_empty_when_none_active(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)
    await store.save(_PERSONA, _ALESHA, SulkState(active=False))

    assert await store.active_sulks(_PERSONA) == []


async def test_backfill_owner_copies_legacy_sulk_state(repo: SqliteMemoryRepo) -> None:
    legacy = SqliteSulkStore(repo)
    mid_sulk = SulkState(
        active=True, intensity=0.6, low_streak=4, since=_SINCE, announced=True
    )
    await legacy.save(_PERSONA, mid_sulk)
    store = SqlitePersonSulkStore(repo)

    await store.backfill_owner(_PERSONA, _OWNER)

    # A mid-обида owner keeps his exact state under his sender_id (byte-identical).
    assert await store.load(_PERSONA, _OWNER) == mid_sulk


async def test_backfill_owner_is_idempotent_and_never_resurrects(
    repo: SqliteMemoryRepo,
) -> None:
    legacy = SqliteSulkStore(repo)
    await legacy.save(_PERSONA, SulkState(active=True, intensity=0.9, since=_SINCE))
    store = SqlitePersonSulkStore(repo)
    await store.backfill_owner(_PERSONA, _OWNER)
    # Owner отошёл — his person_sulk row is now the not-sulking default.
    await store.save(_PERSONA, _OWNER, SulkState())

    # A second backfill must NOT resurrect the stale legacy обида.
    await store.backfill_owner(_PERSONA, _OWNER)

    assert await store.load(_PERSONA, _OWNER) == SulkState()


async def test_backfill_owner_no_legacy_row_is_a_noop(repo: SqliteMemoryRepo) -> None:
    store = SqlitePersonSulkStore(repo)

    await store.backfill_owner(_PERSONA, _OWNER)

    assert await store.load(_PERSONA, _OWNER) == SulkState()
    assert await store.active_sulks(_PERSONA) == []


async def test_backfill_owner_unconfigured_owner_is_a_noop(
    repo: SqliteMemoryRepo,
) -> None:
    # Migration guard: an UNCONFIGURED owner (sender id 0) never backfills, even with a
    # live legacy обида — the copy is skipped rather than writing a row under the zero id.
    legacy = SqliteSulkStore(repo)
    await legacy.save(_PERSONA, SulkState(active=True, intensity=0.9, since=_SINCE))
    store = SqlitePersonSulkStore(repo)

    await store.backfill_owner(_PERSONA, 0)

    assert await store.load(_PERSONA, 0) == SulkState()
    assert await store.active_sulks(_PERSONA) == []


async def test_person_sulk_write_never_touches_the_legacy_sulk_state(
    repo: SqliteMemoryRepo,
) -> None:
    # Anti-Exodus, SEPARATE table: a per-person обида lives in `person_sulk`, so saving one
    # leaves the legacy per-persona `sulk_state` row completely untouched (memory/soul/owner
    # v1 state are never mutated by a guest's cooling).
    legacy = SqliteSulkStore(repo)
    owner_v1 = SulkState(active=True, intensity=0.5, low_streak=2, since=_SINCE)
    await legacy.save(_PERSONA, owner_v1)
    store = SqlitePersonSulkStore(repo)

    await store.save(_PERSONA, _ALESHA, SulkState(active=True, intensity=0.7, since=_SINCE))

    # The guest's обида is recorded, and the legacy table is byte-identical (untouched).
    assert (await store.load(_PERSONA, _ALESHA)).active is True
    assert await legacy.load(_PERSONA) == owner_v1
