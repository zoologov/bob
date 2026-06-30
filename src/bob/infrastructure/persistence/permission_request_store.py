# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqlitePermissionRequestStore — durable store for permission-requests (BOB-052 .1).

Persists Bob's pending permission-requests over the ``permission_request`` table: one
row per request ``id``. The domain
:class:`~bob.domain.permission.entities.PermissionRequest` (its
:class:`~bob.domain.permission.state.PermissionState`, requester, original request
text, kind/what) is mapped to and from rows here, so the domain stays I/O-free.

``ensure_schema`` is the idempotent, PRAGMA-guarded migration: a ``CREATE TABLE IF NOT
EXISTS`` (and a guarded index) — additive and non-destructive, a clean no-op once
present. It is also run by :meth:`SqliteMemoryRepo.initialize` via ``schema.sql``;
exposing it here lets the store stand up its own table without depending solely on the
shared schema. ``save`` UPSERTs on ``id``; ``active`` / ``active_for`` list the still
PENDING requests (oldest first); ``set_state`` transitions a row. All SQL is
parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.domain.permission.entities import PermissionRequest
from bob.domain.permission.state import PermissionState

if TYPE_CHECKING:
    import aiosqlite

__all__ = ["SqlitePermissionRequestStore"]

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS permission_request ("
    "id TEXT PRIMARY KEY, "
    "requester_id INTEGER NOT NULL, "
    "requester_name TEXT NOT NULL, "
    "request_text TEXT NOT NULL, "
    "kind TEXT NOT NULL, "
    "what TEXT NOT NULL, "
    "state TEXT NOT NULL, "
    "created_at TEXT NOT NULL"
    ")"
)
_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_permission_request_requester "
    "ON permission_request (requester_id, state)"
)

_COLUMNS = (
    "id, requester_id, requester_name, request_text, kind, what, state, created_at"
)


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqlitePermissionRequestStore:
    """SQLite adapter for Bob's pending permission-requests (BOB-052)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def ensure_schema(self) -> None:
        """Create the ``permission_request`` table + index (idempotent migration).

        ``CREATE TABLE / INDEX IF NOT EXISTS`` — additive, non-destructive, a clean
        no-op once present.
        """
        await self._db().execute(_CREATE_TABLE)
        await self._db().execute(_CREATE_INDEX)
        await self._db().commit()

    async def save(self, request: PermissionRequest) -> None:
        """Persist ``request`` — UPSERT on ``id``."""
        await self._db().execute(
            f"INSERT INTO permission_request ({_COLUMNS}) "  # noqa: S608 — _COLUMNS is a fixed literal, no user data
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "requester_id = excluded.requester_id, "
            "requester_name = excluded.requester_name, "
            "request_text = excluded.request_text, "
            "kind = excluded.kind, "
            "what = excluded.what, "
            "state = excluded.state, "
            "created_at = excluded.created_at",
            (
                request.id,
                request.requester_id,
                request.requester_name,
                request.request_text,
                request.kind,
                request.what,
                request.state.value,
                request.created_at.isoformat(),
            ),
        )
        await self._db().commit()

    async def active(self) -> tuple[PermissionRequest, ...]:
        """Return the still-PENDING requests (oldest first; empty when none)."""
        async with self._db().execute(
            f"SELECT {_COLUMNS} FROM permission_request "  # noqa: S608 — _COLUMNS is a fixed literal, no user data
            "WHERE state = ? ORDER BY created_at, id",
            (PermissionState.PENDING.value,),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_request(row) for row in rows)

    async def active_for(self, requester_id: int) -> tuple[PermissionRequest, ...]:
        """Return the still-PENDING requests of ``requester_id`` (oldest first)."""
        async with self._db().execute(
            f"SELECT {_COLUMNS} FROM permission_request "  # noqa: S608 — _COLUMNS is a fixed literal, no user data
            "WHERE requester_id = ? AND state = ? ORDER BY created_at, id",
            (requester_id, PermissionState.PENDING.value),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_request(row) for row in rows)

    async def set_state(self, request_id: str, state: PermissionState) -> None:
        """Transition the request ``request_id`` to ``state`` (no-op for an unknown id)."""
        await self._db().execute(
            "UPDATE permission_request SET state = ? WHERE id = ?",
            (state.value, request_id),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _row_to_request(row: aiosqlite.Row) -> PermissionRequest:
    """Map a ``permission_request`` row back to its domain :class:`PermissionRequest`."""
    return PermissionRequest(
        id=str(row[0]),
        requester_id=int(row[1]),
        requester_name=str(row[2]),
        request_text=str(row[3]),
        kind=str(row[4]),
        what=str(row[5]),
        state=PermissionState(str(row[6])),
        created_at=datetime.fromisoformat(str(row[7])),
    )
