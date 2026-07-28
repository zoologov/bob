# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=infrastructure

"""SqliteConversationFloorStore — the per-thread conversation-floor adapter (BOB-025).

Realises :class:`bob.conversation.ports.ConversationFloorStore` over the
``conversation_floor`` table: one row per ``(chat_id, thread_id)`` so Bob keeps,
per running exchange, who currently holds the "talking turn". The domain
:class:`~bob.conversation.conversation_floor.ConversationFloor` is mapped to and
from a row here (``holder`` as the enum value, ``since`` as ISO-8601 text), so the
domain stays I/O-free. A thread never seen has no row, so :meth:`load` returns the
default IDLE floor.

``thread_id`` is NOT NULL with a sentinel (``-1``) standing for "no forum topic / main
chat", because SQLite treats NULL as distinct in a PRIMARY KEY (which would break the
UPSERT and the unseen-key lookup); the domain ``None`` is mapped to/from that sentinel
here. The floor advances every turn, so :meth:`save` is an
``INSERT … ON CONFLICT DO UPDATE`` (an UPSERT). All SQL is parameterised (``?``) —
never an f-string.

The ``participants`` set (floor-по-говорящему, BOB-066 .1) round-trips through a nullable
``participants`` TEXT column as a comma-separated list of ids. **Additive:** an empty set
stores ``NULL`` and a ``NULL`` (a legacy row written before the column existed — see the
guarded migration in ``infrastructure.persistence``) loads back as the empty ``()`` =
legacy mode, so old rows stay valid without a backfill.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.conversation.conversation_floor import (
    ConversationFloor,
    FloorHolder,
    idle_floor,
)

if TYPE_CHECKING:
    import aiosqlite

# Sentinel stored for a domain ``thread_id`` of ``None`` (main chat / no forum topic).
# A real Telegram topic id is positive, so a negative sentinel never collides.
_NO_THREAD_SENTINEL = -1


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteConversationFloorStore:
    """SQLite adapter for the per-thread conversation floor (BOB-025)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:
        """Return the persisted floor for the thread, or the default IDLE if unseen."""
        async with self._db().execute(
            "SELECT holder, holder_id, since, idle_streak, participants "
            "FROM conversation_floor WHERE chat_id = ? AND thread_id = ?",
            (chat_id, _thread_key(thread_id)),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return idle_floor()
        return ConversationFloor(
            holder=FloorHolder(str(row[0])),
            holder_id=None if row[1] is None else int(row[1]),
            since=None if row[2] is None else datetime.fromisoformat(str(row[2])),
            idle_streak=int(row[3]),
            participants=_decode_participants(row[4]),
        )

    async def save(
        self, chat_id: int, thread_id: int | None, floor: ConversationFloor
    ) -> None:
        """Persist ``floor`` for the thread — UPSERT, so an advancing floor is updated.

        ``INSERT … ON CONFLICT(chat_id, thread_id) DO UPDATE``: the floor advances every
        turn, so each turn re-saves the newer state (holder / holder_id / since /
        idle_streak), keeping the continuity read current.
        """
        await self._db().execute(
            "INSERT INTO conversation_floor "
            "(chat_id, thread_id, holder, holder_id, since, idle_streak, participants) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, thread_id) DO UPDATE SET "
            "holder = excluded.holder, "
            "holder_id = excluded.holder_id, "
            "since = excluded.since, "
            "idle_streak = excluded.idle_streak, "
            "participants = excluded.participants",
            (
                chat_id,
                _thread_key(thread_id),
                floor.holder.value,
                floor.holder_id,
                None if floor.since is None else floor.since.isoformat(),
                floor.idle_streak,
                _encode_participants(floor.participants),
            ),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _thread_key(thread_id: int | None) -> int:
    """Map a domain ``thread_id`` (``None`` = main chat) to the NOT NULL stored key."""
    return _NO_THREAD_SENTINEL if thread_id is None else thread_id


# Separator for the ``participants`` id list in the nullable TEXT column (ids are ints,
# so a comma never collides). An empty set stores NULL (legacy), never an empty string.
_PARTICIPANT_SEPARATOR = ","


def _encode_participants(participants: tuple[int, ...]) -> str | None:
    """Serialise the participant ids to CSV, or ``None`` for the empty (legacy) set."""
    if not participants:
        return None
    return _PARTICIPANT_SEPARATOR.join(str(pid) for pid in participants)


def _decode_participants(raw: object) -> tuple[int, ...]:
    """Parse the CSV participants column back to a tuple (``NULL`` = empty/legacy)."""
    if raw is None:
        return ()
    return tuple(int(part) for part in str(raw).split(_PARTICIPANT_SEPARATOR))
