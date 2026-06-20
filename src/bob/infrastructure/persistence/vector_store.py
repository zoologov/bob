# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""MemoryVectorStore — the sqlite-vec embedding side of the memory store.

Owns one responsibility: keeping the ``memory_vec`` vec0 virtual table in step
with the memory archive. It loads the loadable ``sqlite-vec`` extension onto the
(aiosqlite) connection, embeds text through the injected
:class:`~bob.domain.ports.Embedder` (BGE-M3, 1024-dim — never Ollama directly),
and inserts the dense vectors keyed back to their source row by ``(source,
src_id)``. Two write paths feed it: an idempotent **backfill** of pre-existing
facts/episodes on :meth:`backfill`, and **on-write** embedding of a freshly
saved fact/episode via :meth:`embed_row`. With no embedder injected it is inert
(graceful keyword-only fallback) — the vector table still exists, just empty.

Hybrid recall (FTS5 + KNN -> RRF) is a *later* bead: this module only populates
the table, it does not query it for relevance.
"""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING, Literal

import sqlite_vec

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

    from bob.domain.ports import Embedder

logger = logging.getLogger(__name__)

# Source-table tags carried in the vec0 partition-key column.
type VectorSource = Literal["semantic", "episodic"]

_SEMANTIC: VectorSource = "semantic"
_EPISODIC: VectorSource = "episodic"

# Backfill embeds in batches to keep a single Embedder round-trip bounded.
_BACKFILL_BATCH = 64


def _pack(vector: Sequence[float]) -> bytes:
    """Pack a float vector into sqlite-vec's little-endian float32 blob format."""
    return struct.pack(f"<{len(vector)}f", *vector)


class MemoryVectorStore:
    """Embeds memory rows into the ``memory_vec`` vec0 table (sqlite-vec)."""

    def __init__(self, conn: aiosqlite.Connection, embedder: Embedder | None) -> None:
        self._conn = conn
        self._embedder = embedder

    async def load_extension(self) -> None:
        """Load sqlite-vec onto the underlying connection (before schema apply).

        Uses aiosqlite's public API — temporarily enabling extension loading and
        running ``load_extension`` on the worker thread — so the ``vec0`` virtual
        table in ``schema.sql`` can be created. Safe to call even with no embedder
        (the table is part of the schema either way).
        """
        await self._conn.enable_load_extension(True)
        try:
            await self._conn.execute("SELECT load_extension(?)", (sqlite_vec.loadable_path(),))
        finally:
            await self._conn.enable_load_extension(False)

    async def backfill(self) -> None:
        """Embed every fact/episode that has no vector yet (idempotent, batched).

        A no-op when no embedder is injected. Mirrors the FTS backfill pattern:
        run on each boot so a db written before embeddings existed (or before an
        embedder was wired) catches up without ever duplicating a vector.
        """
        if self._embedder is None:
            return
        await self._backfill_source(_SEMANTIC, "semantic_memory")
        await self._backfill_source(_EPISODIC, "episodic_log")

    async def embed_row(self, source: VectorSource, src_id: int, content: str) -> None:
        """Embed one freshly-saved row's ``content`` and insert its vector.

        The on-write path: a no-op without an embedder, and skipped if a vector
        for ``(source, src_id)`` already exists (idempotent under retries).
        """
        if self._embedder is None or await self._has_vector(source, src_id):
            return
        vectors = await self._embedder.embed([content])
        if vectors:
            await self._insert(source, src_id, vectors[0])
            await self._conn.commit()

    async def _backfill_source(self, source: VectorSource, table: str) -> None:
        """Backfill all un-embedded rows of one source table in batches."""
        pending = await self._pending_rows(source, table)
        for start in range(0, len(pending), _BACKFILL_BATCH):
            batch = pending[start : start + _BACKFILL_BATCH]
            await self._embed_batch(source, batch)
        if pending:
            await self._conn.commit()

    async def _pending_rows(
        self, source: VectorSource, table: str
    ) -> list[tuple[int, str]]:
        """Rows of ``table`` (id, content) that have no vector for ``source`` yet.

        ``table`` is a fixed internal literal (``semantic_memory`` /
        ``episodic_log``), never user input, so interpolating it into the LEFT
        JOIN is safe; the partition-key value stays parameterised.
        """
        sql = (
            f"SELECT t.id AS id, t.content AS content FROM {table} t "  # noqa: S608
            "LEFT JOIN memory_vec v ON v.source = ? AND v.src_id = t.id "
            "WHERE v.src_id IS NULL ORDER BY t.id"
        )
        async with self._conn.execute(sql, (source,)) as cursor:
            rows = await cursor.fetchall()
        return [(int(row["id"]), str(row["content"])) for row in rows]

    async def _embed_batch(
        self, source: VectorSource, batch: list[tuple[int, str]]
    ) -> None:
        """Embed one batch of (id, content) rows and insert their vectors."""
        if self._embedder is None or not batch:
            return
        vectors = await self._embedder.embed([content for _, content in batch])
        for (src_id, _), vector in zip(batch, vectors, strict=True):
            await self._insert(source, src_id, vector)

    async def _has_vector(self, source: VectorSource, src_id: int) -> bool:
        """Whether a vector for ``(source, src_id)`` already exists."""
        async with self._conn.execute(
            "SELECT 1 FROM memory_vec WHERE source = ? AND src_id = ? LIMIT 1",
            (source, src_id),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _insert(
        self, source: VectorSource, src_id: int, vector: Sequence[float]
    ) -> None:
        """Insert one packed vector for ``(source, src_id)`` (dimension enforced)."""
        await self._conn.execute(
            "INSERT INTO memory_vec (source, src_id, embedding) VALUES (?, ?, ?)",
            (source, src_id, _pack(vector)),
        )

    async def count(self, source: VectorSource | None = None) -> int:
        """Number of stored vectors, optionally restricted to one ``source``."""
        if source is None:
            async with self._conn.execute("SELECT count(*) FROM memory_vec") as cursor:
                row = await cursor.fetchone()
        else:
            async with self._conn.execute(
                "SELECT count(*) FROM memory_vec WHERE source = ?", (source,)
            ) as cursor:
                row = await cursor.fetchone()
        return 0 if row is None else int(row[0])
