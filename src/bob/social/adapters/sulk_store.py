# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SqliteSulkStore — the per-persona обида state adapter (BOB-014 .2b).

Realises :class:`bob.domain.ports.SulkStore` over the ``sulk_state`` table: one row
per ``persona_id`` so Bobiverse replicas each keep their own обида. The domain
:class:`~bob.social.sulk.SulkState` (the active flag, the decaying
intensity, the low/hostile streak, the entry stamp, and the one-shot ``announced``
flag) is mapped to and from a row here, so the domain stays I/O-free.

An unseen persona has no row, so :meth:`load` returns the fresh, not-sulking default
— the application always has something to read. Like the proactivity state a sulk
EVOLVES (it is entered, decays, and exits), so :meth:`save` is an
``INSERT … ON CONFLICT DO UPDATE`` (an UPSERT) that overwrites the row with the newer
state each tick. Crucially this carries NO memory and NO soul (anti-Exodus) — only the
affect state. All SQL is parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.social.sulk import SulkState

if TYPE_CHECKING:
    import aiosqlite

__all__ = ["SqliteSulkStore"]

# A fresh persona has never been hurt: not sulking, zero intensity, no streak.
_DEFAULT_STATE = SulkState()


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteSulkStore:
    """SQLite adapter for the per-persona обида state (BOB-014 .2b)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str) -> SulkState:
        """Return the persisted обида state for ``persona_id`` (fresh if unseen).

        An unseen persona yields the not-sulking default (no row), so the engine and
        the recovery tick always have something to read.
        """
        async with self._db().execute(
            "SELECT active, intensity, low_streak, since, announced "
            "FROM sulk_state WHERE persona_id = ?",
            (persona_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return _DEFAULT_STATE
        return SulkState(
            active=bool(row[0]),
            intensity=float(row[1]),
            low_streak=int(row[2]),
            since=_parse_ts(row[3]),
            announced=bool(row[4]),
        )

    async def save(self, persona_id: str, state: SulkState) -> None:
        """Persist ``state`` for ``persona_id`` — UPSERT, so обида evolves in place.

        ``INSERT … ON CONFLICT(persona_id) DO UPDATE``: each tick re-saves the newer
        state (entered, decayed, or exited), so the обида's progress is kept current.
        """
        await self._db().execute(
            "INSERT INTO sulk_state "
            "(persona_id, active, intensity, low_streak, since, announced) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id) DO UPDATE SET "
            "active = excluded.active, "
            "intensity = excluded.intensity, "
            "low_streak = excluded.low_streak, "
            "since = excluded.since, "
            "announced = excluded.announced",
            (
                persona_id,
                int(state.active),
                state.intensity,
                state.low_streak,
                _format_ts(state.since),
                int(state.announced),
            ),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _format_ts(value: datetime | None) -> str | None:
    """Render a timezone-aware datetime as ISO-8601 text (``None`` passes through)."""
    return None if value is None else value.isoformat()


def _parse_ts(raw: object) -> datetime | None:
    """Parse an ISO-8601 text marker back into a datetime (``None`` passes through)."""
    return None if raw is None else datetime.fromisoformat(str(raw))
