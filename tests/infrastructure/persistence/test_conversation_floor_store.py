# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteConversationFloorStore — the per-thread floor adapter (BOB-025).

Round-trips the domain :class:`ConversationFloor` into a per-(chat_id, thread_id)
SQLite row: the default IDLE for a thread never seen, the save→load round-trip (BOB
holder + holder_id + since + idle_streak), that a later save UPSERTs the row (the
floor advances every turn), per-thread isolation, the ``thread_id=None`` (main chat)
sentinel mapping, and survival across a restart. Keyed by the THREAD, since the floor
is a property of one running exchange, not of a person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.personality.conversation_floor import (
    ConversationFloor,
    FloorHolder,
    idle_floor,
)
from bob.infrastructure.persistence.conversation_floor_store import (
    SqliteConversationFloorStore,
)
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path

_CHAT = 555
_THREAD = 7
_OTHER_THREAD = 9
_GUEST_ID = 300
_SINCE = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_idle_for_unseen_thread(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)

    assert await store.load(_CHAT, _THREAD) == idle_floor()


async def test_save_then_load_round_trips_bob_floor(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)
    floor = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_SINCE, idle_streak=1
    )

    await store.save(_CHAT, _THREAD, floor)

    assert await store.load(_CHAT, _THREAD) == floor


async def test_save_then_load_round_trips_other_floor(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)
    floor = ConversationFloor(
        holder=FloorHolder.OTHER,
        holder_id=_GUEST_ID,
        since=_SINCE,
        idle_streak=0,
    )

    await store.save(_CHAT, _THREAD, floor)

    assert await store.load(_CHAT, _THREAD) == floor


async def test_save_upserts_an_advancing_floor(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)
    await store.save(
        _CHAT,
        _THREAD,
        ConversationFloor(
            holder=FloorHolder.BOB, holder_id=None, since=_SINCE, idle_streak=0
        ),
    )

    # The floor advances every turn — a later save overwrites the row.
    advanced = ConversationFloor(
        holder=FloorHolder.IDLE, holder_id=None, since=None, idle_streak=0
    )
    await store.save(_CHAT, _THREAD, advanced)

    assert await store.load(_CHAT, _THREAD) == advanced


async def test_is_per_thread_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)
    floor = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_SINCE, idle_streak=0
    )

    await store.save(_CHAT, _THREAD, floor)

    assert await store.load(_CHAT, _THREAD) == floor
    assert await store.load(_CHAT, _OTHER_THREAD) == idle_floor()


async def test_none_thread_id_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteConversationFloorStore(repo)
    floor = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_SINCE, idle_streak=2
    )

    await store.save(_CHAT, None, floor)

    assert await store.load(_CHAT, None) == floor
    # The main-chat (None) key is distinct from a real topic id.
    assert await store.load(_CHAT, _THREAD) == idle_floor()


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    floor = ConversationFloor(
        holder=FloorHolder.OTHER, holder_id=_GUEST_ID, since=_SINCE, idle_streak=0
    )

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteConversationFloorStore(first).save(_CHAT, None, floor)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteConversationFloorStore(second).load(_CHAT, None)
    await second.close()

    assert loaded == floor
