# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""MemoryVectorStore — the sqlite-vec embedding side of the memory store.

Owns one responsibility: keeping the ``memory_vec`` vec0 virtual table in step
with the memory archive. It loads the loadable ``sqlite-vec`` extension onto the
(aiosqlite) connection, embeds text through the injected
:class:`~bob.memory.ports.Embedder` (BGE-M3, 1024-dim — never Ollama directly),
and inserts the dense vectors keyed back to their source row by ``(source,
src_id)``. Two write paths feed it: an idempotent **backfill** of pre-existing
facts/episodes on :meth:`backfill`, and **on-write** embedding of a freshly
saved fact/episode via :meth:`embed_row`. With no embedder injected it is inert
(graceful keyword-only fallback) — the vector table still exists, just empty.

Which rows already have a vector is answered from an id set read once per
source and kept in step on insert: vec0 cannot index ``src_id``, so any SQL
lookup by it is a full table scan (BOB-124).

It also serves the *read* side of semantic recall: :meth:`knn` runs a sqlite-vec
KNN over ``memory_vec``, joins each hit back to its source row's content, and
returns the nearest neighbours (vector distance, ascending). The RRF fusion of
this list with FTS5 keyword hits lives in the hybrid-recall adapter, not here.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import sqlite_vec

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

    from bob.memory.ports import Embedder

logger = logging.getLogger(__name__)

# Source-table tags carried in the vec0 partition-key column.
type VectorSource = Literal["semantic", "episodic"]

_SEMANTIC: VectorSource = "semantic"
_EPISODIC: VectorSource = "episodic"

# Backfill embeds in batches to keep a single Embedder round-trip bounded.
_BACKFILL_BATCH = 64

# Which source table a vector's content lives in (a fixed internal mapping, never
# user input — safe to interpolate into the KNN JOIN). Maps the vec0 partition key
# to its (table, category-column) pair so each hit carries a matching source tag.
_SOURCE_TABLES: dict[VectorSource, tuple[str, str]] = {
    _SEMANTIC: ("semantic_memory", "category"),
    _EPISODIC: ("episodic_log", "event_type"),
}

# Per-source extra WHERE predicate applied to the KNN join (a fixed internal SQL
# literal, never user input). For the semantic source, exclude facts merged by
# BOB-021 dedup (``superseded_by`` set) so a near-duplicate folded into a canonical
# fact never resurfaces in recall. Other sources have no extra filter.
_SOURCE_FILTERS: dict[VectorSource, str] = {
    _SEMANTIC: "t.superseded_by IS NULL",
}


@dataclass(frozen=True)
class BackfillTally:
    """What one source's boot backfill found: its rows and how many lacked a vector."""

    source: VectorSource
    rows: int
    missing: int


def _pack(vector: Sequence[float]) -> bytes:
    """Pack a float vector into sqlite-vec's little-endian float32 blob format."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _distance(hit: dict[str, object]) -> float:
    """KNN distance of a hit (lower is nearer); coerced from the SQL row."""
    return float(str(hit["distance"]))


class MemoryVectorStore:
    """Embeds memory rows into the ``memory_vec`` vec0 table (sqlite-vec)."""

    def __init__(self, conn: aiosqlite.Connection, embedder: Embedder | None) -> None:
        self._conn = conn
        self._embedder = embedder
        # Per-source ids that already have a vector, read once from ``memory_vec``
        # and kept in step by :meth:`_insert` — this store is the table's only
        # writer. vec0 cannot index ``src_id``, so every SQL lookup by it is a
        # full table scan (BOB-124); the set replaces one scan per check.
        self._embedded: dict[VectorSource, set[int]] = {}

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

    async def backfill(self) -> tuple[BackfillTally, ...]:
        """Embed every fact/episode that has no vector yet (idempotent, batched).

        A no-op when no embedder is injected (empty result). Mirrors the FTS
        backfill pattern: run on each boot so a db written before embeddings
        existed (or before an embedder was wired) catches up without ever
        duplicating a vector. Returns one tally per source for the boot log.
        """
        if self._embedder is None:
            return ()
        return (
            await self._backfill_source(_SEMANTIC, "semantic_memory"),
            await self._backfill_source(_EPISODIC, "episodic_log"),
        )

    async def embed_row(self, source: VectorSource, src_id: int, content: str) -> None:
        """Embed one freshly-saved row's ``content`` and insert its vector.

        The on-write path: a no-op without an embedder, and skipped if a vector
        for ``(source, src_id)`` already exists (idempotent under retries). The
        embedding is **best-effort** — if the embedder is unavailable at runtime
        (Ollama down) the embed is skipped and logged, never crashing the write, so
        recall degrades to keyword-only rather than the save failing.
        """
        if self._embedder is None or await self._has_vector(source, src_id):
            return
        vectors = await self._safe_embed([content])
        if vectors:
            await self._insert(source, src_id, vectors[0])
            await self._conn.commit()

    async def _backfill_source(self, source: VectorSource, table: str) -> BackfillTally:
        """Backfill all un-embedded rows of one source table in batches."""
        rows, pending = await self._pending_rows(source, table)
        for start in range(0, len(pending), _BACKFILL_BATCH):
            batch = pending[start : start + _BACKFILL_BATCH]
            await self._embed_batch(source, batch)
        if pending:
            await self._conn.commit()
        return BackfillTally(source=source, rows=rows, missing=len(pending))

    async def _pending_rows(
        self, source: VectorSource, table: str
    ) -> tuple[int, list[tuple[int, str]]]:
        """Row count of ``table`` and its rows (id, content) with no vector yet.

        The anti-join runs in Python, never in SQL against ``memory_vec``: ``src_id``
        is a vec0 metadata column with no index, so a ``LEFT JOIN`` on it re-scans
        the table for every source row — quadratic, hours of CPU on a 27 k-row
        archive at every boot (BOB-124). Instead the embedded ids are read once,
        linearly, into a set, and each source row is checked against it.

        ``table`` is a fixed internal literal (``semantic_memory`` /
        ``episodic_log``), never user input, so interpolating it is safe; the
        partition-key value stays parameterised.
        """
        embedded = await self._embedded_ids(source)
        sql = f"SELECT id, content FROM {table} ORDER BY id"  # noqa: S608
        async with self._conn.execute(sql) as cursor:
            rows = list(await cursor.fetchall())
        pending = [
            (int(row["id"]), str(row["content"]))
            for row in rows
            if int(row["id"]) not in embedded
        ]
        return len(rows), pending

    async def _embedded_ids(self, source: VectorSource) -> set[int]:
        """Source-row ids that already have a vector for ``source`` (cached).

        Read on first use with one linear pass over ``memory_vec``. Outside a KNN
        query the partition-key filter does not narrow that pass: measured on the
        production db, the 45-vector ``semantic`` partition costs 85 ms and the
        27 502-vector ``episodic`` one 131 ms, so a pass is paid once per source,
        never per row or per write.
        """
        cached = self._embedded.get(source)
        if cached is None:
            async with self._conn.execute(
                "SELECT src_id FROM memory_vec WHERE source = ?", (source,)
            ) as cursor:
                rows = await cursor.fetchall()
            cached = {int(row[0]) for row in rows}
            self._embedded[source] = cached
        return cached

    async def _embed_batch(
        self, source: VectorSource, batch: list[tuple[int, str]]
    ) -> None:
        """Embed one batch of (id, content) rows and insert their vectors.

        Best-effort: an embedder that is unavailable at runtime (Ollama down) yields
        no vectors and the batch is skipped (logged), so a boot-time backfill never
        crashes the app — the archive simply stays keyword-only until the embedder
        is reachable on a later boot.
        """
        if self._embedder is None or not batch:
            return
        vectors = await self._safe_embed([content for _, content in batch])
        if not vectors:
            # Embedder unavailable (already logged): leave the batch un-embedded.
            return
        for (src_id, _), vector in zip(batch, vectors, strict=True):
            await self._insert(source, src_id, vector)

    async def _safe_embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts``, returning ``[]`` (logged) on any embedder failure.

        Guards only the embedder call (the runtime "Ollama down" fault). A wrong
        dimension is NOT caught here: the embedder still returns a vector, and the
        SQL insert enforces the schema's width — a misconfiguration must surface.
        """
        if self._embedder is None:
            return []
        try:
            return await self._embedder.embed(texts)
        except Exception:
            logger.warning(
                "embedder unavailable; skipping embedding (keyword-only memory)",
                exc_info=True,
            )
            return []

    async def _has_vector(self, source: VectorSource, src_id: int) -> bool:
        """Whether a vector for ``(source, src_id)`` already exists.

        Answered from the cached id set: a ``WHERE src_id = ?`` lookup on vec0 is a
        full table scan (119 ms per saved message on the production db, BOB-124).
        """
        return src_id in await self._embedded_ids(source)

    async def _insert(
        self, source: VectorSource, src_id: int, vector: Sequence[float]
    ) -> None:
        """Insert one packed vector for ``(source, src_id)`` (dimension enforced).

        The id joins the cached set only after the insert succeeded, so a rejected
        vector (wrong width) never reads as embedded.
        """
        embedded = await self._embedded_ids(source)
        await self._conn.execute(
            "INSERT INTO memory_vec (source, src_id, embedding) VALUES (?, ?, ?)",
            (source, src_id, _pack(vector)),
        )
        embedded.add(src_id)

    async def knn(self, vector: Sequence[float], k: int) -> list[dict[str, object]]:
        """Top-``k`` nearest neighbours of ``vector`` across both sources.

        Runs a sqlite-vec KNN per source partition, joins each hit back to its
        source row's ``content``, merges the two lists and returns the globally
        nearest ``k`` by vector distance (ascending). Each item carries its
        ``content``, ``source`` tag, the source row's ``category``, its ``ts``
        (ISO-8601 string — the age signal BOB-021's surface_old leans on), its
        ``visibility`` (BOB-066 2.6 scope-provenance the recall filter reads) and the
        raw ``distance``. Empty when ``k <= 0`` (no neighbours requested).
        """
        if k <= 0:
            return []
        packed = _pack(vector)
        merged: list[dict[str, object]] = []
        for source, (table, category_col) in _SOURCE_TABLES.items():
            merged.extend(await self._knn_source(source, table, category_col, packed, k))
        merged.sort(key=_distance)
        return merged[:k]

    async def _knn_source(
        self,
        source: VectorSource,
        table: str,
        category_col: str,
        packed: bytes,
        k: int,
    ) -> list[dict[str, object]]:
        """KNN within one source partition, joined to its content/category.

        ``table`` / ``category_col`` and the per-source filter are fixed internal
        literals from ``_SOURCE_TABLES`` / ``_SOURCE_FILTERS`` (never user input),
        so interpolating them into the JOIN is safe; the query vector, partition key
        and ``k`` stay parameterised. The semantic filter excludes facts superseded
        by BOB-021 dedup so a merged near-duplicate never resurfaces. Each hit also
        carries its ``ts`` (both source tables have it) — the age signal surface_old
        reads to bias toward an old-but-relevant memory.
        """
        extra = _SOURCE_FILTERS.get(source)
        extra_clause = f" AND {extra}" if extra else ""
        sql = (
            "SELECT t.content AS content, "  # noqa: S608 — literals are internal, not user input
            f"t.{category_col} AS category, t.ts AS ts, ? AS source, "
            "t.visibility AS visibility, v.distance AS distance "
            f"FROM memory_vec v JOIN {table} t ON t.id = v.src_id "
            f"WHERE v.source = ? AND v.embedding MATCH ? AND k = ?{extra_clause} "
            "ORDER BY v.distance"
        )
        async with self._conn.execute(sql, (source, source, packed, k)) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

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
