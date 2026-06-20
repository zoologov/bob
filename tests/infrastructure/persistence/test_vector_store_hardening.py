# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening edge cases for MemoryVectorStore (BOB-011 BEAD-07 coverage).

Drives the boundary branches of the sqlite-vec store directly (not through the
repo): a ``knn`` with no neighbours requested, the inert no-embedder paths, and an
empty backfill batch — the cheap guards that keep the vector half degrading
gracefully to keyword-only memory. No network: the store is exercised over a real
temp SQLite connection with the sqlite-vec extension loaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bob.infrastructure.persistence.vector_store import MemoryVectorStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_DIM = 4


class _Embedder:
    """Trivial embedder returning a fixed small vector per text (no network)."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


async def _open(tmp_path: Path) -> aiosqlite.Connection:
    """Open a temp connection with sqlite-vec loaded and a small memory_vec table."""
    conn = await aiosqlite.connect(tmp_path / "vec.db")
    conn.row_factory = aiosqlite.Row
    store = MemoryVectorStore(conn, embedder=_Embedder())
    await store.load_extension()
    await conn.execute(
        f"CREATE VIRTUAL TABLE memory_vec USING vec0("
        f"source text partition key, src_id integer, embedding float[{_DIM}])"
    )
    await conn.commit()
    return conn


async def test_knn_with_non_positive_k_requests_no_neighbours(tmp_path: Path) -> None:
    # Arrange: a store whose table holds one vector.
    conn = await _open(tmp_path)
    store = MemoryVectorStore(conn, embedder=_Embedder())
    try:
        await store.embed_row("semantic", 1, "anything")

        # Act / Assert: asking for k<=0 neighbours short-circuits to an empty list
        # (no KNN query) rather than erroring on a zero-row request.
        assert await store.knn([1.0, 0.0, 0.0, 0.0], k=0) == []
        assert await store.knn([1.0, 0.0, 0.0, 0.0], k=-3) == []
    finally:
        await conn.close()


async def test_backfill_with_no_pending_rows_is_a_noop(tmp_path: Path) -> None:
    # Arrange: an embedder-backed store over EMPTY source tables (no rows to embed),
    # so each source's backfill batch is empty.
    conn = await _open(tmp_path)
    await conn.execute("CREATE TABLE semantic_memory (id integer primary key, content text)")
    await conn.execute("CREATE TABLE episodic_log (id integer primary key, content text)")
    await conn.commit()
    store = MemoryVectorStore(conn, embedder=_Embedder())
    try:
        # Act: backfill runs over empty tables (the empty-batch guard path).
        await store.backfill()

        # Assert: nothing embedded, no crash.
        assert await store.count() == 0
    finally:
        await conn.close()


async def test_inert_store_without_embedder_embeds_nothing(tmp_path: Path) -> None:
    # Arrange: NO embedder injected -> every write path is inert (keyword-only mode).
    conn = await _open(tmp_path)
    store = MemoryVectorStore(conn, embedder=None)
    try:
        # Act: on-write, backfill, and a direct embed all short-circuit.
        await store.embed_row("semantic", 1, "ignored")
        await store.backfill()

        # Assert: the table stays empty (the no-embedder guards held).
        assert await store.count() == 0
    finally:
        await conn.close()


async def test_count_restricted_to_a_single_source(tmp_path: Path) -> None:
    # Arrange: vectors in both partitions.
    conn = await _open(tmp_path)
    store = MemoryVectorStore(conn, embedder=_Embedder())
    try:
        await store.embed_row("semantic", 1, "a")
        await store.embed_row("episodic", 1, "b")

        # Act / Assert: per-source counts isolate each partition; total sums them.
        assert await store.count(source="semantic") == 1
        assert await store.count(source="episodic") == 1
        assert await store.count() == 2
    finally:
        await conn.close()


async def test_embed_row_is_idempotent_for_same_source_and_id(tmp_path: Path) -> None:
    # Arrange
    conn = await _open(tmp_path)
    store = MemoryVectorStore(conn, embedder=_Embedder())
    try:
        # Act: embedding the same (source, src_id) twice must not duplicate.
        await store.embed_row("semantic", 7, "first")
        await store.embed_row("semantic", 7, "again")

        # Assert: exactly one vector for that row (idempotent under retries).
        assert await store.count(source="semantic") == 1
    finally:
        await conn.close()


async def test_embed_batch_guards_empty_batch_and_missing_embedder(
    tmp_path: Path,
) -> None:
    # The internal batch-embed guards (defensive against an empty batch or a missing
    # embedder) must short-circuit cleanly so a backfill never embeds a zero-row
    # batch or dereferences a None embedder. Drive the guards directly.
    conn = await _open(tmp_path)
    try:
        # No embedder: _embed_batch returns immediately, embedding nothing.
        inert = MemoryVectorStore(conn, embedder=None)
        await inert._embed_batch("semantic", [(1, "x")])
        assert await inert.count() == 0

        # Empty batch with a healthy embedder: still a no-op.
        live = MemoryVectorStore(conn, embedder=_Embedder())
        await live._embed_batch("semantic", [])
        assert await live.count() == 0

        # _safe_embed with no embedder yields no vectors (the keyword-only guard).
        assert await inert._safe_embed(["x"]) == []
    finally:
        await conn.close()


@pytest.mark.parametrize("source", ["semantic", "episodic"])
async def test_count_is_zero_on_a_fresh_table(tmp_path: Path, source: str) -> None:
    # Arrange / Act / Assert: an empty partition reports zero, not None/error.
    conn = await _open(tmp_path)
    store = MemoryVectorStore(conn, embedder=_Embedder())
    try:
        assert await store.count(source=source) == 0  # type: ignore[arg-type]
    finally:
        await conn.close()
