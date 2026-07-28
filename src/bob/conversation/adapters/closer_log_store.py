# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=infrastructure

"""SqliteCloserLog — the cross-session closer ring adapter (BOB-061 .1).

Realises :class:`bob.domain.ports.CloserLog` over the ``closer_log`` table: a bounded,
LOCAL ring of Bob's recent reply CLOSERS. It closes gap 1 (cross-session sparsity) — a
signature closer-tic that recurs ONCE PER SESSION over days is invisible to the live
session window (0-1 occurrences, below the tic bar), so it slips through. Persisting the
normalised closer after each reply lets the near-verbatim tic detector
(:func:`~bob.conversation.conversation.is_recurring_closer_tic`) see the motif
scattered across sessions and finally catch it.

Deliberately tiny and PRIVATE — only normalised closer PHRASES (never full replies),
capped at a small ``cap`` so the ring self-trims (the oldest fall off on append). Rows
are ordered by the autoincrement ``id`` (insertion order = recency). ``append`` logs one
closer and prunes to the cap; ``recent(k)`` returns the last ``k`` closers most-recent
first. ``ensure_schema`` is the idempotent, additive migration (``CREATE TABLE IF NOT
EXISTS``), also run by :meth:`SqliteMemoryRepo.initialize` via ``schema.sql``. All SQL is
parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import aiosqlite

__all__ = ["SqliteCloserLog"]

# The default ring cap: ~30 of Bob's most-recent closers. Wide enough that a
# once-per-session motif recurring ~4x/week accumulates several occurrences, but small
# enough to stay a minimal, private trace (not a full reply archive).
_DEFAULT_CAP = 30

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS closer_log ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "closer TEXT NOT NULL"
    ")"
)


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteCloserLog:
    """SQLite adapter for Bob's bounded cross-session closer ring (BOB-061 .1)."""

    def __init__(self, repo: _ConnectionProvider, *, cap: int = _DEFAULT_CAP) -> None:
        self._repo = repo
        self._cap = max(1, cap)

    async def ensure_schema(self) -> None:
        """Create the ``closer_log`` table (idempotent migration).

        ``CREATE TABLE IF NOT EXISTS`` — additive, non-destructive, a clean no-op once
        present.
        """
        await self._db().execute(_CREATE_TABLE)
        await self._db().commit()

    async def append(self, closer: str) -> None:
        """Append ``closer`` to the ring, then prune to the cap (blank is ignored).

        A blank/whitespace-only closer carries no motif, so it is never logged. After
        the insert the ring is trimmed to the newest ``cap`` rows, so the oldest closers
        fall off — the log stays bounded and private.
        """
        text = closer.strip()
        if not text:
            return
        db = self._db()
        await db.execute("INSERT INTO closer_log (closer) VALUES (?)", (text,))
        await db.execute(
            "DELETE FROM closer_log WHERE id NOT IN ("
            "SELECT id FROM closer_log ORDER BY id DESC LIMIT ?"
            ")",
            (self._cap,),
        )
        await db.commit()

    async def recent(self, k: int) -> tuple[str, ...]:
        """Return the last ``k`` logged closers, most-recent first (empty when none)."""
        if k <= 0:
            return ()
        async with self._db().execute(
            "SELECT closer FROM closer_log ORDER BY id DESC LIMIT ?", (k,)
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection
