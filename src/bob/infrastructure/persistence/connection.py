# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteConnection — the shared SQLite connection/schema kernel.

The pure-I/O foundation every durable store in the codebase sits on: it opens the
(aiosqlite) connection in WAL mode with ``foreign_keys`` on, loads the loadable
``sqlite-vec`` extension so the ``memory_vec`` vec0 table can be created, applies
the bundled ``schema.sql`` idempotently, and exposes the live connection through
the ``connection`` **seam** that the memory adapter and the 13 per-module stores
(personality / social / proactivity / coding / conversation) all read. It also
owns the generic key/value store (:meth:`kv_set` / :meth:`kv_get`).

It carries NO memory (episodic/semantic/vector) logic and NO domain entities —
that realisation lives in :class:`bob.memory.adapters.SqliteMemoryRepo`, which
holds a reference to this kernel and works through the ``connection`` seam. Being
pure connection/schema I/O, it stays in ``bob.infrastructure.persistence`` (the
runtime composition root merely *creates* it and injects it into every store).
"""

from __future__ import annotations

import logging
from importlib import resources
from typing import TYPE_CHECKING

import aiosqlite
import sqlite_vec

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_RESOURCE = "schema.sql"


class SqliteConnection:
    """The shared SQLite connection + schema kernel (WAL, sqlite-vec, kv)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> Path:
        """The filesystem path of the underlying database file."""
        return self._db_path

    async def initialize(self) -> None:
        """Open the connection (WAL) and apply the schema idempotently.

        On first call the connection is opened, ``PRAGMA journal_mode=WAL`` and
        ``foreign_keys=ON`` are set, and the loadable ``sqlite-vec`` extension is
        loaded onto it (the ``memory_vec`` vec0 table in ``schema.sql`` needs it).
        The bundled schema is then executed — ``CREATE TABLE IF NOT EXISTS`` makes
        this a clean no-op on a re-run — and the proactivity migration is applied.
        """
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            await self._load_vec_extension()
        await self._conn.executescript(_load_schema())
        await self._migrate_pursuit_stopped()
        await self._migrate_conversation_floor_participants()
        await self._migrate_person_relationship_gender()
        await self._migrate_first_impression_display_name()
        await self._conn.commit()
        logger.info("SqliteConnection initialised at %s", self._db_path)

    async def _load_vec_extension(self) -> None:
        """Load sqlite-vec onto the connection (before the schema is applied).

        Uses aiosqlite's public API — temporarily enabling extension loading and
        running ``load_extension`` on the worker thread — so the ``vec0`` virtual
        table in ``schema.sql`` can be created. A capability of the connection
        itself, so it belongs to the kernel that owns the connection.
        """
        await self._db().enable_load_extension(True)
        try:
            await self._db().execute(
                "SELECT load_extension(?)", (sqlite_vec.loadable_path(),)
            )
        finally:
            await self._db().enable_load_extension(False)

    async def _migrate_pursuit_stopped(self) -> None:
        """Add ``proactivity_state.pursuit_stopped`` to a pre-existing DB (BOB-015 .2).

        The goal-pursuit kill-switch flag (``/goals stop``). ``CREATE TABLE IF NOT
        EXISTS`` never alters an already-present table, so a DB written before this
        column existed would lack it. This guarded ``ALTER`` adds it only when
        missing — additive and non-destructive: existing rows take the column
        default (0, i.e. pursuit NOT stopped). A clean no-op once present.

        # BOB-062: proactivity-specific, future relocation. Kept in the kernel for
        now because the kernel is the schema/migration owner (it applies the whole
        ``schema.sql`` in one ``executescript``); a later slice may move it into the
        proactivity module.
        """
        if "pursuit_stopped" in await self._proactivity_columns():
            return
        await self._db().execute(
            "ALTER TABLE proactivity_state "
            "ADD COLUMN pursuit_stopped INTEGER NOT NULL DEFAULT 0"
        )

    async def _proactivity_columns(self) -> set[str]:
        """Names of the columns currently on ``proactivity_state``.

        # BOB-062: proactivity-specific, future relocation (see
        :meth:`_migrate_pursuit_stopped`).
        """
        async with self._db().execute("PRAGMA table_info(proactivity_state)") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_conversation_floor_participants(self) -> None:
        """Add ``conversation_floor.participants`` to a pre-existing DB (BOB-066 .1).

        Floor-по-говорящему: the CSV of ids whose ambient replies Bob holds as his own
        (who is really in the exchange). ``CREATE TABLE IF NOT EXISTS`` never alters an
        already-present table, so a DB written before this column existed would lack it.
        This guarded ``ALTER`` adds it only when missing — additive and non-destructive: a
        legacy row takes ``NULL``, which the store reads back as the empty ``()`` = legacy
        mode (any participant continues, exactly the pre-BOB-066 floor). A clean no-op once
        present. Kept in the kernel (the schema/migration owner) beside
        :meth:`_migrate_pursuit_stopped`.
        """
        if "participants" in await self._conversation_floor_columns():
            return
        await self._db().execute(
            "ALTER TABLE conversation_floor ADD COLUMN participants TEXT"
        )

    async def _conversation_floor_columns(self) -> set[str]:
        """Names of the columns currently on ``conversation_floor`` (BOB-066 .1)."""
        async with self._db().execute(
            "PRAGMA table_info(conversation_floor)"
        ) as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_person_relationship_gender(self) -> None:
        """Add ``person_relationship.gender`` to a pre-existing DB (BOB-078 A).

        The self-identified grammatical-gender lean (a REAL in ``[-1, 1]`` read only
        from a person's own self-presentation). ``CREATE TABLE IF NOT EXISTS`` never
        alters an already-present table, so a DB written before this column existed
        would lack it. This guarded ``ALTER`` adds it only when missing — additive and
        non-destructive: a legacy row takes ``NULL``, which the store reads back as
        ``Gender.UNKNOWN`` (Bob forces no gender). A clean no-op once present. Kept in
        the kernel (the schema/migration owner) beside the other guarded ALTERs.
        """
        if "gender" in await self._person_relationship_columns():
            return
        await self._db().execute(
            "ALTER TABLE person_relationship ADD COLUMN gender REAL"
        )

    async def _person_relationship_columns(self) -> set[str]:
        """Names of the columns currently on ``person_relationship`` (BOB-078 A)."""
        async with self._db().execute(
            "PRAGMA table_info(person_relationship)"
        ) as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_first_impression_display_name(self) -> None:
        """Add ``first_impression.display_name`` to a pre-existing DB (BOB-080).

        The person's name kept as a first-class field so a roster can NAME people who
        are not the current writer. ``CREATE TABLE IF NOT EXISTS`` never alters an
        already-present table, so a DB written before this column existed would lack it.
        This guarded ``ALTER`` adds it only when missing — additive and non-destructive:
        a legacy row takes ``NULL``, from which the domain parses the name out of the
        ``"{name} — …"`` note as a fallback. A clean no-op once present. Kept in the
        kernel (the schema/migration owner) beside the other guarded ALTERs.
        """
        if "display_name" in await self._first_impression_columns():
            return
        await self._db().execute(
            "ALTER TABLE first_impression ADD COLUMN display_name TEXT"
        )

    async def _first_impression_columns(self) -> set[str]:
        """Names of the columns currently on ``first_impression`` (BOB-080)."""
        async with self._db().execute(
            "PRAGMA table_info(first_impression)"
        ) as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

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

    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteConnection used before initialize()")
        return self._conn

    @property
    def connection(self) -> aiosqlite.Connection:
        """The live connection — THE SEAM shared by the memory adapter + all stores."""
        return self._db()


def _load_schema() -> str:
    """Read the bundled ``schema.sql`` from the package."""
    return resources.files(__package__).joinpath(_SCHEMA_RESOURCE).read_text(encoding="utf-8")
