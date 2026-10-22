# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boot-time vector backfill at production scale (BOB-124).

The backfill runs on every boot, before Bob polls Telegram. Finding the rows that
still lack a vector used to be a ``LEFT JOIN memory_vec`` on ``src_id`` — a column
the sqlite-vec ``vec0`` table cannot index, so the join re-scanned the whole
partition for every source row: 27 k x 27 k on the production db, hours of CPU
before the first reply. These tests run on the REAL sqlite + sqlite-vec schema (a
fake store would model none of that cost) and pin two things: a fully embedded
archive of 30 000 episodes is checked within a fixed wall-clock budget, and the
rows reported missing are exactly the ones lacking a vector in their OWN source.
"""

from __future__ import annotations

import asyncio
import struct
import time
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.connection import SqliteConnection
from bob.memory.adapters.vector_store import MemoryVectorStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import aiosqlite

_DIM = 1024  # schema.sql: memory_vec.embedding float[1024]
_ROWS = 30_000
# A fully embedded fact partition next to the episodes: the old join cost
# facts x the whole vec0 table (the partition filter does not narrow it), so a
# regression confined to the semantic side must break the boot budget too.
_FACTS = 500
# Budgets: medians measured on the dev machine (Apple-silicon mac, 2026-10-22, 5 runs
# each, idle, fresh store per run): the boot backfill over this archive takes
# 0.26 s, and 100 on-write embeds plus the count 0.30 s — almost all of it the one
# initial pass over vec0, not the inserts.
# Review measured 0.50 s for 20 writes under load (20 processes on 10 cores);
# the 2-core CI runner is slower per core still. The budgets keep >= 10x headroom
# over the idle medians, while the old SQL costs minutes for the backfill and at
# least 100 x 0.14 s = 14 s for the writes, so both still bite.
_BUDGET_S = 5.0
# Fresh episodes saved after boot; each one used to pay a full vec0 scan on write.
_FRESH = 100
_WRITE_BUDGET_S = 3.0
_TS = "2026-10-22T00:00:00+00:00"
# A handful of distinct vectors, cycled: the cost under test is the id lookup, not
# the vector content, and packing 30 000 x 1024 floats would dominate the setup.
_VECTORS = [struct.pack(f"<{_DIM}f", *([float(k + 1)] * _DIM)) for k in range(8)]


class _CountingEmbedder:
    """Embedder that records each call; a fully embedded archive must make none."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.5] * _DIM for _ in texts]


async def _open(tmp_path: Path) -> aiosqlite.Connection:
    """A real Bob db: the production schema with the sqlite-vec extension loaded."""
    kernel = SqliteConnection(tmp_path / "bob.db")
    await kernel.initialize()
    return kernel.connection


async def _seed_episodes(conn: aiosqlite.Connection, ids: Sequence[int]) -> None:
    await conn.executemany(
        "INSERT INTO episodic_log (id, ts, event_type, content) VALUES (?, ?, 'message', ?)",
        [(i, _TS, f"episode {i}") for i in ids],
    )


async def _seed_facts(conn: aiosqlite.Connection, ids: Sequence[int]) -> None:
    await conn.executemany(
        "INSERT INTO semantic_memory (id, ts, category, content) VALUES (?, ?, 'pref', ?)",
        [(i, _TS, f"fact {i}") for i in ids],
    )


async def _seed_vectors(
    conn: aiosqlite.Connection, source: str, ids: Sequence[int]
) -> None:
    await conn.executemany(
        "INSERT INTO memory_vec (source, src_id, embedding) VALUES (?, ?, ?)",
        [(source, i, _VECTORS[i % len(_VECTORS)]) for i in ids],
    )


async def _embedded_archive(tmp_path: Path) -> aiosqlite.Connection:
    """A real db: ``_ROWS`` episodes and ``_FACTS`` facts, every one with its vector."""
    conn = await _open(tmp_path)
    ids = range(1, _ROWS + 1)
    await _seed_episodes(conn, ids)
    await _seed_vectors(conn, "episodic", ids)
    fact_ids = range(1, _FACTS + 1)
    await _seed_facts(conn, fact_ids)
    await _seed_vectors(conn, "semantic", fact_ids)
    await conn.commit()
    return conn


async def test_backfill_of_a_fully_embedded_archive_fits_the_boot_budget(
    tmp_path: Path,
) -> None:
    # Arrange: 30 000 episodes and 500 facts, every one already embedded (the steady
    # state of a long-lived Bob: the boot backfill has nothing to do and must find
    # that out fast, for BOTH sources).
    conn = await _embedded_archive(tmp_path)
    embedder = _CountingEmbedder()
    store = MemoryVectorStore(conn, embedder)

    # Act: the boot backfill, cut off at the budget (the old query would run for
    # minutes; interrupting it lets the test fail instead of hanging the suite).
    started = time.perf_counter()
    try:
        await asyncio.wait_for(store.backfill(), timeout=_BUDGET_S)
    except TimeoutError:
        await conn.interrupt()
        pytest.fail(
            f"backfill over {_ROWS} episodes + {_FACTS} facts, all embedded, exceeded "
            f"the {_BUDGET_S} s boot budget"
        )
    finally:
        await conn.close()
    elapsed = time.perf_counter() - started

    # Assert: within budget, and nothing was re-embedded.
    assert elapsed < _BUDGET_S
    assert embedder.texts == []


async def test_embedding_fresh_episodes_into_a_large_archive_fits_the_write_budget(
    tmp_path: Path,
) -> None:
    # Arrange: the same embedded archive; Bob now saves new episodes, and each
    # save embeds its row on write after checking that no vector exists yet. That
    # check must not cost a scan of the whole archive per message.
    conn = await _embedded_archive(tmp_path)
    fresh = range(_ROWS + 1, _ROWS + 1 + _FRESH)
    await _seed_episodes(conn, fresh)
    await conn.commit()
    embedder = _CountingEmbedder()
    store = MemoryVectorStore(conn, embedder)

    async def save_turns() -> None:
        for i in fresh:
            await store.embed_row("episodic", i, f"episode {i}")

    # Act
    started = time.perf_counter()
    try:
        await asyncio.wait_for(save_turns(), timeout=_WRITE_BUDGET_S)
        embedded = await store.count("episodic")
    except TimeoutError:
        await conn.interrupt()
        pytest.fail(
            f"embedding {_FRESH} fresh episodes into a {_ROWS}-row archive exceeded "
            f"the {_WRITE_BUDGET_S} s write budget"
        )
    finally:
        await conn.close()
    elapsed = time.perf_counter() - started

    # Assert: every fresh episode embedded once, within budget.
    assert elapsed < _WRITE_BUDGET_S
    assert len(embedder.texts) == _FRESH
    assert embedded == _ROWS + _FRESH


async def test_backfill_embeds_exactly_the_rows_missing_from_their_own_source(
    tmp_path: Path,
) -> None:
    # Arrange: interleaved gaps in both sources, with ids that collide across them —
    # episode 2 lacks a vector even though FACT 2 has one, and vice versa for 3.
    conn = await _open(tmp_path)
    await _seed_episodes(conn, [1, 2, 3, 4, 5])
    await _seed_facts(conn, [1, 2, 3, 4])
    await _seed_vectors(conn, "episodic", [1, 3, 5])
    await _seed_vectors(conn, "semantic", [1, 2, 4])
    await conn.commit()
    embedder = _CountingEmbedder()
    store = MemoryVectorStore(conn, embedder)

    try:
        # Act
        await store.backfill()

        # Assert: only the per-source gaps were embedded, in id order, once each.
        assert embedder.texts == ["fact 3", "episode 2", "episode 4"]
        assert await store.count("semantic") == 4
        assert await store.count("episodic") == 5
    finally:
        await conn.close()
