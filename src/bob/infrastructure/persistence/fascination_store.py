# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteFascinationStore — the per-persona current-fascination adapter.

Realises :class:`bob.domain.ports.FascinationStore` over the ``fascination_state``
table: one row per ``persona_id`` so Bobiverse replicas each keep their own
current passion. The domain :class:`~bob.domain.personality.fascination.Fascination`
is mapped to and from a row here (intensity as a REAL, ``created_at`` as ISO-8601
text) so the domain stays I/O-free. An unseen persona — or one whose fascination
was retired and not yet replaced — has no row, so :meth:`load` returns ``None``.
All SQL is parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.domain.personality.fascination import Fascination

if TYPE_CHECKING:
    import aiosqlite


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteFascinationStore:
    """SQLite adapter for Bob's per-persona current fascination (BOB-020)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str) -> Fascination | None:
        """Return the persisted fascination for ``persona_id``, or ``None`` if none."""
        async with self._db().execute(
            "SELECT topic, intensity, created_at "
            "FROM fascination_state WHERE persona_id = ?",
            (persona_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Fascination(
            topic=str(row[0]),
            intensity=float(row[1]),
            created_at=datetime.fromisoformat(str(row[2])),
        )

    async def save(self, persona_id: str, fascination: Fascination) -> None:
        """Persist ``fascination`` for ``persona_id`` (replacing any prior one)."""
        await self._db().execute(
            "INSERT INTO fascination_state (persona_id, topic, intensity, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(persona_id) DO UPDATE SET "
            "topic = excluded.topic, "
            "intensity = excluded.intensity, "
            "created_at = excluded.created_at",
            (
                persona_id,
                fascination.topic,
                fascination.intensity,
                fascination.created_at.isoformat(),
            ),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection
