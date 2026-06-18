# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteMemoryRepo — the durable SQLite-backed store for Bob's memory & state.

Realises :class:`bob.domain.ports.MemoryRepo` and is the single home for SQL in
the codebase. The schema (``schema.sql``) is applied idempotently on
:meth:`initialize`, the connection runs in WAL mode for concurrent reads, and
every statement is parameterised (``?``) — never an f-string. Domain entities
(:class:`~bob.domain.memory.entities.EpisodicEvent` /
:class:`~bob.domain.memory.entities.SemanticFact`) are mapped to and from rows
here so the domain stays I/O-free.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

    from bob.domain.memory.entities import EpisodicEvent, SemanticFact

logger = logging.getLogger(__name__)

# A JSON-serialisable state blob (mood / relationship).
type StateBlob = Mapping[str, object]

_SCHEMA_RESOURCE = "schema.sql"
_MOOD_ROW_ID = 1
_RELATIONSHIP_ROW_ID = 1


class SqliteMemoryRepo:
    """SQLite adapter for episodic/semantic memory and personality state."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the connection (WAL) and apply the schema (idempotent)."""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_load_schema())
        await self._conn.commit()
        logger.info("SqliteMemoryRepo initialised at %s", self._db_path)

    async def close(self) -> None:
        """Close the underlying connection (idempotent)."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def journal_mode(self) -> str:
        """Return the active SQLite journal mode (expected ``wal``)."""
        async with self._db().execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        return "" if row is None else str(row[0])

    # --- Episodic memory ------------------------------------------------------

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        """Append one episodic event (raw mapping form) to durable storage."""
        await self._db().execute(
            "INSERT INTO episodic_log (ts, event_type, content, mood_snapshot, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                episode["ts"],
                episode["event_type"],
                episode["content"],
                episode.get("mood_snapshot"),
                episode.get("tags", ""),
            ),
        )
        await self._db().commit()

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        """Append an :class:`EpisodicEvent` domain entity."""
        await self.save_episode(
            {
                "ts": event.ts.isoformat(),
                "event_type": event.event_type,
                "content": event.content,
                "mood_snapshot": event.mood_snapshot,
                "tags": ",".join(event.tags),
            }
        )

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent episodes (newest first)."""
        async with self._db().execute(
            "SELECT ts, event_type, content, mood_snapshot, tags "
            "FROM episodic_log ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Semantic memory ------------------------------------------------------

    async def save_fact(self, fact: SemanticFact) -> None:
        """Persist a semantic fact (FTS index is updated by trigger)."""
        await self._db().execute(
            "INSERT INTO semantic_memory (ts, category, content, confidence) VALUES (?, ?, ?, ?)",
            (fact.ts.isoformat(), fact.category, fact.content, fact.confidence),
        )
        await self._db().commit()

    async def load_facts(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent semantic facts (newest first)."""
        async with self._db().execute(
            "SELECT ts, category, content, confidence "
            "FROM semantic_memory ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Mood -----------------------------------------------------------------

    async def set_mood(self, state: StateBlob, *, at: datetime) -> None:
        """Replace the current mood and append a snapshot to history."""
        blob = json.dumps(dict(state))
        ts = at.isoformat()
        await self._db().execute(
            "INSERT INTO mood_state (id, state, ts) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state, ts = excluded.ts",
            (_MOOD_ROW_ID, blob, ts),
        )
        await self._db().execute(
            "INSERT INTO mood_history (state, ts) VALUES (?, ?)", (blob, ts)
        )
        await self._db().commit()

    async def get_mood(self) -> dict[str, object] | None:
        """Return the current mood blob, or ``None`` if never set."""
        async with self._db().execute(
            "SELECT state FROM mood_state WHERE id = ?", (_MOOD_ROW_ID,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _loads_object(row[0])

    async def mood_history(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent mood snapshots (newest first)."""
        async with self._db().execute(
            "SELECT state, ts FROM mood_history ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"state": _loads_object(row[0]), "ts": row[1]} for row in rows]

    # --- Taste axes -----------------------------------------------------------

    async def set_taste_axis(
        self,
        axis: str,
        *,
        value: float,
        conviction: float,
        experience_count: int,
    ) -> None:
        """Upsert one taste axis (no duplicate rows for the same axis)."""
        await self._db().execute(
            "INSERT INTO taste_axes (axis, value, conviction, experience_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(axis) DO UPDATE SET "
            "value = excluded.value, conviction = excluded.conviction, "
            "experience_count = excluded.experience_count",
            (axis, value, conviction, experience_count),
        )
        await self._db().commit()

    async def load_taste_axes(self) -> Sequence[Mapping[str, object]]:
        """Return all taste axes ordered by name."""
        async with self._db().execute(
            "SELECT axis, value, conviction, experience_count FROM taste_axes ORDER BY axis"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Relationship ---------------------------------------------------------

    async def set_relationship(self, state: StateBlob) -> None:
        """Replace the relationship state (single-row JSON blob)."""
        await self._db().execute(
            "INSERT INTO relationship (id, state) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state",
            (_RELATIONSHIP_ROW_ID, json.dumps(dict(state))),
        )
        await self._db().commit()

    async def get_relationship(self) -> dict[str, object] | None:
        """Return the relationship blob, or ``None`` if never set."""
        async with self._db().execute(
            "SELECT state FROM relationship WHERE id = ?", (_RELATIONSHIP_ROW_ID,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _loads_object(row[0])

    # --- Key/value ------------------------------------------------------------

    async def kv_set(self, key: str, value: str) -> None:
        """Set ``key`` to ``value`` in the generic key/value store."""
        await self._db().execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db().commit()

    async def kv_get(self, key: str) -> str | None:
        """Return the value for ``key``, or ``None`` if absent."""
        async with self._db().execute("SELECT value FROM kv WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row[0])

    # --- Internals ------------------------------------------------------------

    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteMemoryRepo used before initialize()")
        return self._conn

    @property
    def connection(self) -> aiosqlite.Connection:
        """The live connection (for collaborators such as the recall adapter)."""
        return self._db()


def _load_schema() -> str:
    """Read the bundled ``schema.sql`` from the package."""
    return resources.files(__package__).joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")


def _loads_object(raw: object) -> dict[str, object]:
    """Decode a JSON object blob into a dict (defensive on row types)."""
    decoded = json.loads(str(raw))
    if not isinstance(decoded, dict):
        raise ValueError("expected a JSON object in state blob")
    return decoded
