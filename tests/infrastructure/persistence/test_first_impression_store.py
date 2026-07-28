# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteFirstImpressionStore — the per-sender first-impression adapter.

Round-trips the domain :class:`FirstImpression` (sender_id, first_seen_at, note)
into a per-``sender_id`` SQLite row: the ``None`` default for an unseen sender, the
save→load round-trip, that a save does NOT clobber the original first-seen instant
(an impression is formed once), per-sender isolation, and survival across a restart.
Keyed by sender_id so it works for owner / known / guest / bot alike — this is
per-PERSON data (about them), not owner-private memory.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.adapters.first_impression_store import (
    SqliteFirstImpressionStore,
)
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from pathlib import Path

_SENDER = 4242
_OTHER_SENDER = 9999
_SEEN = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_none_for_unseen_sender(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)

    assert await store.load(_SENDER) is None


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    impression = FirstImpression(
        sender_id=_SENDER, first_seen_at=_SEEN, note="незнакомец, присматриваюсь"
    )

    await store.save(impression)
    loaded = await store.load(_SENDER)

    assert loaded == impression


async def test_save_keeps_the_original_first_seen(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    first = FirstImpression(sender_id=_SENDER, first_seen_at=_SEEN, note="первый раз")

    await store.save(first)
    # A second save for the same sender must NOT move the original first-seen instant
    # nor overwrite the note (the impression is formed once, on first contact).
    await store.save(
        FirstImpression(sender_id=_SENDER, first_seen_at=_LATER, note="второй раз")
    )

    assert await store.load(_SENDER) == first


async def test_is_per_sender_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteFirstImpressionStore(repo)
    one = FirstImpression(sender_id=_SENDER, first_seen_at=_SEEN, note="он")

    await store.save(one)

    assert await store.load(_SENDER) == one
    assert await store.load(_OTHER_SENDER) is None


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    impression = FirstImpression(
        sender_id=_SENDER, first_seen_at=_SEEN, note="запомнил"
    )

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteFirstImpressionStore(first).save(impression)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteFirstImpressionStore(second).load(_SENDER)
    await second.close()

    assert loaded == impression
