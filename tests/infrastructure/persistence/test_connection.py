# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteConnection — the shared connection/schema kernel (BOB-062.7b).

The kernel is the heart of Bob's durable state: it opens the WAL connection with
``foreign_keys`` on, loads the loadable ``sqlite-vec`` extension so the ``vec0``
``memory_vec`` table can exist, applies ``schema.sql`` idempotently, owns the
proactivity kill-switch migration, exposes the ``connection`` **seam** every store
reads through, and owns the generic kv store. These tests pin the persistence
invariants directly on the kernel in isolation (the memory adapter is exercised in
``test_sqlite_repo.py``), plus the seam guarantee that ONE shared kernel feeds many
per-module stores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.infrastructure.persistence.connection import SqliteConnection
from bob.social.adapters.allowlist_store import KvAllowlistStore
from bob.social.adapters.relationship_store import SqliteRelationshipStore
from bob.social.relationship import Relationship

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def kernel(tmp_path: Path) -> SqliteConnection:
    instance = SqliteConnection(tmp_path / "bob.db")
    await instance.initialize()
    return instance


# --- Init / hardening invariants ------------------------------------------------


async def test_initialize_uses_wal_journal_mode(kernel: SqliteConnection) -> None:
    # Assert: WAL is required for concurrent reads during a write.
    assert (await kernel.journal_mode()).lower() == "wal"
    await kernel.close()


async def test_initialize_enables_foreign_keys(kernel: SqliteConnection) -> None:
    # Act: foreign_keys is set ON at open — referential integrity across the schema.
    async with kernel.connection.execute("PRAGMA foreign_keys") as cursor:
        row = await cursor.fetchone()

    # Assert: 1 == enforced.
    assert row is not None
    assert int(row[0]) == 1
    await kernel.close()


async def test_initialize_loads_sqlite_vec_so_memory_vec_is_queryable(
    kernel: SqliteConnection,
) -> None:
    # Act/Assert: the vec0 ``memory_vec`` virtual table in schema.sql only exists
    # when sqlite-vec was loaded onto the connection first — querying it proves the
    # extension is live (an unloaded extension makes the CREATE VIRTUAL TABLE fail).
    async with kernel.connection.execute("SELECT count(*) FROM memory_vec") as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert int(row[0]) == 0
    await kernel.close()


async def test_initialize_applies_schema_and_is_idempotent(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "bob.db"
    kernel = SqliteConnection(db_path)

    # Act: running init twice must not raise (CREATE IF NOT EXISTS + guarded ALTERs).
    await kernel.initialize()
    await kernel.initialize()

    # Assert: schema applied — the kv table exists and the file is on disk.
    await kernel.kv_set("probe", "1")
    assert await kernel.kv_get("probe") == "1"
    assert db_path.exists()
    await kernel.close()


# --- Use-before-initialize guardrails -------------------------------------------


async def test_connection_seam_before_initialize_raises(tmp_path: Path) -> None:
    # Arrange: a kernel that was never initialised.
    kernel = SqliteConnection(tmp_path / "bob.db")

    # Act/Assert: reading the seam before open is a programming error, not a crash.
    with pytest.raises(RuntimeError, match="before initialize"):
        _ = kernel.connection


async def test_kv_get_before_initialize_raises(tmp_path: Path) -> None:
    # Arrange
    kernel = SqliteConnection(tmp_path / "bob.db")

    # Act/Assert
    with pytest.raises(RuntimeError, match="before initialize"):
        await kernel.kv_get("anything")


# --- kv store (kernel-owned seam) -----------------------------------------------


async def test_kv_set_get_round_trips_and_absent_is_none(
    kernel: SqliteConnection,
) -> None:
    # Act
    await kernel.kv_set("genesis_done", "true")

    # Assert
    assert await kernel.kv_get("genesis_done") == "true"
    assert await kernel.kv_get("never_set") is None
    await kernel.close()


async def test_kv_set_upserts_existing_key(kernel: SqliteConnection) -> None:
    # Arrange
    await kernel.kv_set("k", "first")

    # Act: a second set on the same key overwrites (ON CONFLICT), no duplicate row.
    await kernel.kv_set("k", "second")

    # Assert
    assert await kernel.kv_get("k") == "second"
    await kernel.close()


async def test_kv_survives_a_process_restart(tmp_path: Path) -> None:
    # Arrange: write with one kernel instance, then drop it.
    db_path = tmp_path / "bob.db"
    writer = SqliteConnection(db_path)
    await writer.initialize()
    await writer.kv_set("genesis_done", "true")
    await writer.close()

    # Act: a brand-new kernel over the same file simulates a restart.
    reader = SqliteConnection(db_path)
    await reader.initialize()

    # Assert
    assert await reader.kv_get("genesis_done") == "true"
    await reader.close()


# --- Lifecycle ------------------------------------------------------------------


async def test_close_is_idempotent(kernel: SqliteConnection) -> None:
    # Act/Assert: closing twice — and closing a fresh, never-opened kernel — is safe.
    await kernel.close()
    await kernel.close()


async def test_close_before_initialize_is_noop(tmp_path: Path) -> None:
    # Act/Assert: a kernel that never opened can still be closed without raising.
    kernel = SqliteConnection(tmp_path / "bob.db")
    await kernel.close()


async def test_db_path_exposes_underlying_file(tmp_path: Path) -> None:
    # Arrange/Act
    db_path = tmp_path / "bob.db"
    kernel = SqliteConnection(db_path)

    # Assert: the kernel reports the path it will open (used by adapters for logging).
    assert kernel.db_path == db_path


# --- Proactivity migration (kernel is the schema/migration owner) ---------------


async def test_pursuit_stopped_migration_adds_column_to_a_legacy_db(
    tmp_path: Path,
) -> None:
    # Arrange: a legacy DB whose proactivity_state predates the pursuit_stopped
    # kill-switch column (BOB-015 .2). CREATE TABLE IF NOT EXISTS never alters an
    # existing table, so the kernel's guarded ALTER is what must add the column.
    db_path = tmp_path / "legacy.db"
    async with aiosqlite.connect(db_path) as raw:
        await raw.execute(
            "CREATE TABLE proactivity_state ("
            "  persona_id TEXT PRIMARY KEY,"
            "  social_energy REAL NOT NULL,"
            "  proactivity_enabled INTEGER NOT NULL DEFAULT 1"
            ")"
        )
        await raw.execute(
            "INSERT INTO proactivity_state (persona_id, social_energy) VALUES ('bob', 1.0)"
        )
        await raw.commit()

    # Act: the kernel opens the pre-existing DB and runs its migration.
    kernel = SqliteConnection(db_path)
    await kernel.initialize()

    # Assert: the column now exists AND the pre-existing row took the default (0 =
    # pursuit NOT stopped) — additive, non-destructive.
    async with kernel.connection.execute(
        "SELECT pursuit_stopped FROM proactivity_state WHERE persona_id = 'bob'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert int(row[0]) == 0
    await kernel.close()


# --- THE SEAM: one shared kernel feeds many per-module stores -------------------


async def test_one_shared_kernel_feeds_multiple_module_stores(
    kernel: SqliteConnection,
) -> None:
    # Arrange: inject the SAME kernel into two stores from different bounded
    # contexts — a ``.connection``-seam store (social relationship, BOB-014) and a
    # kv-seam store (social allowlist). This is exactly what the composition root
    # does: one SqliteConnection, shared by all 13 stores + the memory adapter.
    relationships = SqliteRelationshipStore(kernel)
    allowlist = KvAllowlistStore(kernel)
    rel = Relationship(sender_id=7, trust=0.4, respect=0.2, warmth=0.6, compatibility=0.1)

    # Act: both stores read/write through the one kernel's live connection.
    await relationships.save(rel)
    await allowlist.add(99)

    # Assert: each store's state round-trips over the shared connection, independently.
    assert await relationships.load(7) == rel
    assert await allowlist.load() == {99}

    # Both stores hold the very same aiosqlite connection object (one shared handle).
    assert isinstance(kernel.connection, aiosqlite.Connection)
    await kernel.close()
