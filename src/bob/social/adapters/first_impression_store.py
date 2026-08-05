# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SqliteFirstImpressionStore — the per-sender first-impression adapter (BOB-019).

Realises :class:`bob.social.ports.FirstImpressionStore` over the ``first_impression``
table: one row per ``sender_id`` so Bob keeps a LIGHT first read on each person he
meets. The domain :class:`~bob.social.first_impression.FirstImpression`
is mapped to and from a row here (``first_seen_at`` as ISO-8601 text) so the domain
stays I/O-free. An unseen sender has no row, so :meth:`load` returns ``None``.

The impression is formed ONCE, on first contact: :meth:`save` never overwrites a
returning sender's original first-seen instant, note or display name — that is what lets
Bob *recognise* them later. The single exception is the ``@ник`` (BOB-090.B3), which is
refreshed rather than frozen: a handle changes over a person's life, and everyone Bob
already knows predates the column. Keyed by ``sender_id`` it covers owner / known /
guest / bot alike; this is
per-PERSON data (about them), NOT owner-private memory. All SQL is parameterised
(``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    import aiosqlite


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteFirstImpressionStore:
    """SQLite adapter for Bob's per-sender first impression (BOB-019)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, sender_id: int) -> FirstImpression | None:
        """Return the persisted first impression for ``sender_id``, or ``None``."""
        async with self._db().execute(
            "SELECT sender_id, first_seen_at, note, display_name, username "
            "FROM first_impression WHERE sender_id = ?",
            (sender_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_impression(row)

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        """Return the ``limit`` most-recently-met impressions (newest first).

        The FIRST recency query over ``first_impression`` — ``ORDER BY first_seen_at
        DESC`` rather than the per-sender point look-up ``load`` does — so a roster can
        recall who lately turned up in the room (BOB-080). All SQL is parameterised.
        """
        async with self._db().execute(
            "SELECT sender_id, first_seen_at, note, display_name, username "
            "FROM first_impression ORDER BY first_seen_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_impression(row) for row in rows]

    async def save(self, impression: FirstImpression) -> None:
        """Persist ``impression`` once — only the ``@ник`` is ever refreshed.

        ``INSERT … ON CONFLICT(sender_id) DO UPDATE``: the impression is formed on first
        contact and kept as-is, so a returning sender's original first-seen instant, note
        and display name survive (that is what lets Bob recognise them later) — none of
        those columns is in the ``SET``.

        🔴 ``username`` (BOB-090.B3) is the ONE exception, and deliberately so. A handle
        is not an impression: people change it, and — decisive here — everyone Bob already
        knows was recorded BEFORE the column existed, so a DO-NOTHING save would leave
        every existing person handle-less forever and «@Норман» would stay unfixable. The
        update is guarded by ``excluded.username IS NOT NULL``, so a turn that carries no
        handle (Telegram is not obliged to send one) never ERASES a known one.
        """
        await self._db().execute(
            "INSERT INTO first_impression "
            "(sender_id, first_seen_at, note, display_name, username) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(sender_id) DO UPDATE SET username = excluded.username "
            "WHERE excluded.username IS NOT NULL",
            (
                impression.sender_id,
                impression.first_seen_at.isoformat(),
                impression.note,
                impression.display_name,
                impression.username,
            ),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _row_to_impression(row: aiosqlite.Row) -> FirstImpression:
    """Map a ``first_impression`` row to the domain VO (NULL name/handle → ``None``)."""
    display_name = row[3]
    username = row[4]
    return FirstImpression(
        sender_id=int(row[0]),
        first_seen_at=datetime.fromisoformat(str(row[1])),
        note=str(row[2]),
        display_name=None if display_name is None else str(display_name),
        username=None if username is None else str(username),
    )
