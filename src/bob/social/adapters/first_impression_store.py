# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SqliteFirstImpressionStore — the per-sender first-impression adapter (BOB-019).

Realises :class:`bob.domain.ports.FirstImpressionStore` over the ``first_impression``
table: one row per ``sender_id`` so Bob keeps a LIGHT first read on each person he
meets. The domain :class:`~bob.social.first_impression.FirstImpression`
is mapped to and from a row here (``first_seen_at`` as ISO-8601 text) so the domain
stays I/O-free. An unseen sender has no row, so :meth:`load` returns ``None``.

The impression is formed ONCE, on first contact: :meth:`save` is an
``INSERT … ON CONFLICT DO NOTHING``, so a returning sender's original first-seen
instant and note are never overwritten — that is what lets Bob *recognise* them
later. Keyed by ``sender_id`` it covers owner / known / guest / bot alike; this is
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
            "SELECT sender_id, first_seen_at, note "
            "FROM first_impression WHERE sender_id = ?",
            (sender_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return FirstImpression(
            sender_id=int(row[0]),
            first_seen_at=datetime.fromisoformat(str(row[1])),
            note=str(row[2]),
        )

    async def save(self, impression: FirstImpression) -> None:
        """Persist ``impression`` once — a known sender is never overwritten.

        ``INSERT … ON CONFLICT(sender_id) DO NOTHING``: the impression is formed on
        first contact and kept as-is, so a returning sender's original first-seen
        instant and note survive (that is what lets Bob recognise them later).
        """
        await self._db().execute(
            "INSERT INTO first_impression (sender_id, first_seen_at, note) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(sender_id) DO NOTHING",
            (
                impression.sender_id,
                impression.first_seen_at.isoformat(),
                impression.note,
            ),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection
