# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqliteCloserLog — кросс-сессионный кольцевой персист closer-ов (BOB-061 .1).

``append`` дописывает нормализованный closer, ``recent(k)`` отдаёт последние k
(most-recent first); кольцо ограничено (cap) — старые вытесняются; пустой/пробельный
closer игнорируется; переживает рестарт; миграция идемпотентна (повторный
``ensure_schema`` — no-op).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.closer_log_store import SqliteCloserLog
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_append_then_recent_round_trips_most_recent_first(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo)
    await store.append("мне так спокойнее")
    await store.append("пусть остаётся как есть")

    assert await store.recent(2) == ("пусть остаётся как есть", "мне так спокойнее")


async def test_recent_limits_to_k(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo)
    for i in range(5):
        await store.append(f"концовка {i}")

    assert await store.recent(2) == ("концовка 4", "концовка 3")


async def test_recent_of_empty_log_is_empty(repo: SqliteMemoryRepo) -> None:
    assert await SqliteCloserLog(repo).recent(5) == ()


async def test_recent_with_non_positive_k_is_empty(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo)
    await store.append("что-то")
    assert await store.recent(0) == ()
    assert await store.recent(-1) == ()


async def test_ring_evicts_oldest_beyond_cap(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo, cap=3)
    for i in range(6):
        await store.append(f"c{i}")

    # Only the newest `cap` survive; the oldest fell off the ring.
    assert await store.recent(10) == ("c5", "c4", "c3")


async def test_blank_closer_is_ignored(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo)
    await store.append("")
    await store.append("   ")
    await store.append("настоящая концовка")

    assert await store.recent(10) == ("настоящая концовка",)


async def test_ensure_schema_is_idempotent(repo: SqliteMemoryRepo) -> None:
    store = SqliteCloserLog(repo)
    # initialize() already created the table; calling ensure_schema again must not raise.
    await store.ensure_schema()
    await store.ensure_schema()
    await store.append("концовка")
    assert await store.recent(1) == ("концовка",)


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    repo1 = SqliteMemoryRepo(db)
    await repo1.initialize()
    await SqliteCloserLog(repo1).append("мне так спокойнее")
    await repo1.close()

    repo2 = SqliteMemoryRepo(db)
    await repo2.initialize()
    recent = await SqliteCloserLog(repo2).recent(5)
    await repo2.close()

    assert recent == ("мне так спокойнее",)
