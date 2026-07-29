# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SqlitePersonSulkStore — the per-(persona, sender) обида adapter (BOB-066 Срез 2.5).

Realises :class:`bob.social.ports.PersonSulkStore` over the ``person_sulk`` table: one
row per ``(persona_id, sender_id)`` so Bob can cool toward a SINGLE participant of a
multi-party thread without it touching his tone toward anyone else. The domain
:class:`~bob.social.sulk.SulkState` (the active flag, the decaying intensity, the
low/hostile streak, the entry stamp, and the one-shot ``announced`` flag) is mapped to
and from a row here, so the domain stays I/O-free.

An unseen ``(persona, sender)`` has no row, so :meth:`load` returns the fresh, not-sulking
default. Like the per-persona sulk an обида EVOLVES (it is entered, decays, and exits), so
:meth:`save` is an ``INSERT … ON CONFLICT DO UPDATE`` (an UPSERT). :meth:`active_sulks`
lists the currently-обижен senders so the recovery tick iterates only the active ones.
:meth:`backfill_owner` copies the legacy per-persona ``sulk_state`` row into ``person_sulk``
ONCE (idempotent, existence-guarded — it never resurrects a stale обида) so a mid-обида
owner keeps his state byte-identical across the upgrade. Carries NO memory and NO soul
(anti-Exodus). All SQL is parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.social.sulk import SulkState

if TYPE_CHECKING:
    import aiosqlite

__all__ = ["SqlitePersonSulkStore"]

# A fresh (persona, sender) has never been hurt: not sulking, zero intensity, no streak.
_DEFAULT_STATE = SulkState()


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqlitePersonSulkStore:
    """SQLite adapter for the per-(persona, sender) обида state (BOB-066 Срез 2.5)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str, sender_id: int) -> SulkState:
        """Return the обида state for ``(persona_id, sender_id)`` (fresh if unseen).

        An unseen pair yields the not-sulking default (no row), so the engine and the
        recovery tick always have something to read.
        """
        async with self._db().execute(
            "SELECT active, intensity, low_streak, since, announced "
            "FROM person_sulk WHERE persona_id = ? AND sender_id = ?",
            (persona_id, sender_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return _DEFAULT_STATE
        return _row_to_state(row)

    async def save(self, persona_id: str, sender_id: int, state: SulkState) -> None:
        """Persist ``state`` for ``(persona_id, sender_id)`` — UPSERT, so обида evolves.

        ``INSERT … ON CONFLICT(persona_id, sender_id) DO UPDATE``: each turn/tick re-saves
        the newer state (entered, decayed, or exited), so the обида's progress is current.
        """
        await self._upsert(persona_id, sender_id, state)
        await self._db().commit()

    async def active_sulks(self, persona_id: str) -> list[int]:
        """Return the sender ids ``persona_id`` is CURRENTLY обижен at (active rows).

        The recovery tick iterates ONLY these, so a not-sulking (persona, sender) is
        never re-loaded/re-saved. Ordered by ``sender_id`` for a deterministic read.
        """
        async with self._db().execute(
            "SELECT sender_id FROM person_sulk "
            "WHERE persona_id = ? AND active = 1 ORDER BY sender_id",
            (persona_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]

    async def backfill_owner(self, persona_id: str, owner_sender_id: int) -> None:
        """Copy the legacy ``sulk_state`` row into ``person_sulk`` ONCE (BOB-066 2.5).

        The per-persona ``sulk_state`` (BOB-014) held the OWNER's обида (the owner-gated
        v1). Generalising to per-person, the owner becomes one ``sender_id``; this copies
        his legacy row under ``owner_sender_id`` so a mid-обида owner keeps his exact
        state (byte-identical upgrade). Existence-guarded on the ``person_sulk`` row so it
        is idempotent AND never resurrects a stale обида once the owner has отошёл (a
        subsequent decayed/exited person_sulk row is left untouched). A no-op when there
        is no legacy row or the owner id is unconfigured.
        """
        if owner_sender_id == 0:
            return
        if await self._owner_row_exists(persona_id, owner_sender_id):
            return
        legacy = await self._legacy_row(persona_id)
        if legacy is None:
            return
        await self._upsert(persona_id, owner_sender_id, legacy)
        await self._db().commit()

    async def _owner_row_exists(self, persona_id: str, sender_id: int) -> bool:
        async with self._db().execute(
            "SELECT 1 FROM person_sulk WHERE persona_id = ? AND sender_id = ? LIMIT 1",
            (persona_id, sender_id),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _legacy_row(self, persona_id: str) -> SulkState | None:
        async with self._db().execute(
            "SELECT active, intensity, low_streak, since, announced "
            "FROM sulk_state WHERE persona_id = ?",
            (persona_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _row_to_state(row)

    async def _upsert(self, persona_id: str, sender_id: int, state: SulkState) -> None:
        await self._db().execute(
            "INSERT INTO person_sulk "
            "(persona_id, sender_id, active, intensity, low_streak, since, announced) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, sender_id) DO UPDATE SET "
            "active = excluded.active, "
            "intensity = excluded.intensity, "
            "low_streak = excluded.low_streak, "
            "since = excluded.since, "
            "announced = excluded.announced",
            (
                persona_id,
                sender_id,
                int(state.active),
                state.intensity,
                state.low_streak,
                _format_ts(state.since),
                int(state.announced),
            ),
        )

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _row_to_state(row: aiosqlite.Row) -> SulkState:
    """Map a ``(active, intensity, low_streak, since, announced)`` row to a SulkState."""
    return SulkState(
        active=bool(row[0]),
        intensity=float(row[1]),
        low_streak=int(row[2]),
        since=_parse_ts(row[3]),
        announced=bool(row[4]),
    )


def _format_ts(value: datetime | None) -> str | None:
    """Render a timezone-aware datetime as ISO-8601 text (``None`` passes through)."""
    return None if value is None else value.isoformat()


def _parse_ts(raw: object) -> datetime | None:
    """Parse an ISO-8601 text marker back into a datetime (``None`` passes through)."""
    return None if raw is None else datetime.fromisoformat(str(raw))
