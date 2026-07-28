# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for KvAllowlistStore — the SQLite-backed authorization allowlist.

The allowlist persists in the generic ``kv`` table as a JSON list under a single
key, so ``/authorize`` survives a restart. These tests cover the empty default,
add/remove idempotency, and a fresh store reading the same db after a "restart".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.social.adapters.allowlist_store import KvAllowlistStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_is_empty_by_default(repo: SqliteMemoryRepo) -> None:
    store = KvAllowlistStore(repo)

    assert await store.load() == set()


async def test_add_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = KvAllowlistStore(repo)

    await store.add(42)
    await store.add(7)

    assert await store.load() == {42, 7}


async def test_add_is_idempotent(repo: SqliteMemoryRepo) -> None:
    store = KvAllowlistStore(repo)

    await store.add(42)
    await store.add(42)

    assert await store.load() == {42}


async def test_remove_drops_the_user(repo: SqliteMemoryRepo) -> None:
    store = KvAllowlistStore(repo)
    await store.add(42)
    await store.add(7)

    await store.remove(42)

    assert await store.load() == {7}


async def test_remove_absent_user_is_noop(repo: SqliteMemoryRepo) -> None:
    store = KvAllowlistStore(repo)
    await store.add(7)

    await store.remove(999)

    assert await store.load() == {7}


async def test_allowlist_survives_a_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "bob.db"
    first = SqliteMemoryRepo(db_path)
    await first.initialize()
    await KvAllowlistStore(first).add(42)
    await first.close()

    second = SqliteMemoryRepo(db_path)
    await second.initialize()
    try:
        assert await KvAllowlistStore(second).load() == {42}
    finally:
        await second.close()
