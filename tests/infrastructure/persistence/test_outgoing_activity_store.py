# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for EpisodicOutgoingActivityStore — share of voice off the episodic log."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.presence.adapters.outgoing_activity_store import EpisodicOutgoingActivityStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_CHAT_ID = 555


class _Provider:
    """Minimal connection provider around a live aiosqlite connection."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    @property
    def connection(self) -> aiosqlite.Connection:
        return self._connection


@pytest.fixture
async def conn() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute(
        "CREATE TABLE episodic_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "event_type TEXT NOT NULL, content TEXT NOT NULL, "
        "sender_id INTEGER, bob_message_id INTEGER)"
    )
    await connection.commit()
    yield connection
    await connection.close()


async def _add_turn(
    connection: aiosqlite.Connection,
    *,
    ts: str,
    sender_id: int | None,
    bob_message_id: int | None,
    event_type: str = "message",
) -> None:
    await connection.execute(
        "INSERT INTO episodic_log (ts, event_type, content, sender_id, bob_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts, event_type, "turn", sender_id, bob_message_id),
    )
    await connection.commit()


async def test_empty_log_yields_empty_window(conn: aiosqlite.Connection) -> None:
    # Arrange
    store = EpisodicOutgoingActivityStore(_Provider(conn))

    # Act
    activity = await store.load(_CHAT_ID)

    # Assert: nothing seen ⇒ zero share, no error.
    assert activity.total_seen == 0
    assert activity.share == 0.0


async def test_counts_bob_sent_vs_total_seen(conn: aiosqlite.Connection) -> None:
    # Arrange: 4 turns seen; Bob replied on 2 of them (bob_message_id set).
    await _add_turn(conn, ts="2026-07-29T10:00:00+00:00", sender_id=1, bob_message_id=None)
    await _add_turn(conn, ts="2026-07-29T10:01:00+00:00", sender_id=2, bob_message_id=None)
    await _add_turn(conn, ts="2026-07-29T10:02:00+00:00", sender_id=1, bob_message_id=900)
    await _add_turn(conn, ts="2026-07-29T10:03:00+00:00", sender_id=2, bob_message_id=901)
    store = EpisodicOutgoingActivityStore(_Provider(conn))

    # Act
    activity = await store.load(_CHAT_ID)

    # Assert
    assert activity.total_seen == 4
    assert activity.bob_sent == 2
    assert activity.share == pytest.approx(0.5)
    assert activity.distinct_senders == 2


async def test_only_message_events_count(conn: aiosqlite.Connection) -> None:
    # Arrange: a reflection tick is NOT a conversational turn.
    await _add_turn(conn, ts="2026-07-29T10:00:00+00:00", sender_id=1, bob_message_id=900)
    await _add_turn(
        conn,
        ts="2026-07-29T10:01:00+00:00",
        sender_id=None,
        bob_message_id=None,
        event_type="reflection",
    )
    store = EpisodicOutgoingActivityStore(_Provider(conn))

    # Act
    activity = await store.load(_CHAT_ID)

    # Assert: only the one message turn is seen.
    assert activity.total_seen == 1
    assert activity.bob_sent == 1


async def test_window_size_bounds_the_rolling_count(conn: aiosqlite.Connection) -> None:
    # Arrange: 5 turns, but the window only looks at the last 2.
    for i in range(5):
        await _add_turn(
            conn,
            ts=f"2026-07-29T10:0{i}:00+00:00",
            sender_id=1,
            bob_message_id=(900 + i) if i >= 3 else None,
        )
    store = EpisodicOutgoingActivityStore(_Provider(conn), window_size=2)

    # Act: the last 2 turns (i=3,4) both had Bob replies.
    activity = await store.load(_CHAT_ID)

    # Assert
    assert activity.total_seen == 2
    assert activity.bob_sent == 2
