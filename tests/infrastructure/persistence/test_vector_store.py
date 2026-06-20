# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the sqlite-vec vector store: schema, backfill, and on-write embed.

Drives BEAD-02: the ``memory_vec`` vec0 table is created in the existing SQLite
db, existing facts/episodes are backfilled (idempotently) through the injected
:class:`~bob.domain.ports.Embedder`, and a newly-saved fact/episode is embedded
on write. No network/Ollama — the deterministic :class:`FakeEmbedder` stands in.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.memory.entities import EpisodicEvent, SemanticFact
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from tests.support.fake_embedder import FakeEmbedder

if TYPE_CHECKING:
    from pathlib import Path

_DIM = 1024


def _ts(hour: int = 12) -> datetime:
    return datetime(2026, 6, 18, hour, 0, 0, tzinfo=UTC)


def _fact(content: str) -> SemanticFact:
    return SemanticFact(ts=_ts(), category="pref", content=content)


def _episode(content: str) -> EpisodicEvent:
    return EpisodicEvent(ts=_ts(), event_type="message", content=content)


@pytest.fixture
async def embedder() -> FakeEmbedder:
    return FakeEmbedder(dim=_DIM)


async def test_vec_table_created_when_embedder_injected(
    tmp_path: Path, embedder: FakeEmbedder
) -> None:
    # Arrange / Act
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()

    # Assert: the vec0 virtual table exists and is empty on a fresh db.
    assert await repo.vector_count() == 0
    await repo.close()


async def test_vec_table_created_without_embedder(tmp_path: Path) -> None:
    # Arrange / Act: schema is created even with no embedder (graceful fallback).
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    # Assert: table exists (count works) but nothing is embedded.
    assert await repo.vector_count() == 0
    await repo.close()


async def test_on_write_embeds_new_fact(tmp_path: Path, embedder: FakeEmbedder) -> None:
    # Arrange
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()

    # Act
    await repo.save_fact(_fact("bob loves jazz"))

    # Assert: one semantic vector landed.
    assert await repo.vector_count(source="semantic") == 1
    await repo.close()


async def test_on_write_embeds_new_episode(tmp_path: Path, embedder: FakeEmbedder) -> None:
    # Arrange
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await repo.initialize()

    # Act
    await repo.save_episode_entity(_episode("we talked about the ocean"))

    # Assert
    assert await repo.vector_count(source="episodic") == 1
    await repo.close()


async def test_no_embed_on_write_without_embedder(tmp_path: Path) -> None:
    # Arrange: no embedder -> on-write must not attempt to embed (no crash).
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()

    # Act
    await repo.save_fact(_fact("bob loves jazz"))
    await repo.save_episode_entity(_episode("we talked about the ocean"))

    # Assert
    assert await repo.vector_count() == 0
    await repo.close()


async def test_backfill_embeds_preexisting_rows(tmp_path: Path, embedder: FakeEmbedder) -> None:
    # Arrange: a db written WITHOUT an embedder (legacy rows, no vectors).
    db_path = tmp_path / "bob.db"
    legacy = SqliteMemoryRepo(db_path)
    await legacy.initialize()
    await legacy.save_fact(_fact("bob loves jazz"))
    await legacy.save_fact(_fact("bob hates loud noise"))
    await legacy.save_episode_entity(_episode("we talked about the ocean"))
    await legacy.close()

    # Act: reopen WITH an embedder -> initialize() backfills the archive.
    repo = SqliteMemoryRepo(db_path, embedder=embedder)
    await repo.initialize()

    # Assert: every pre-existing fact + episode now has a vector.
    assert await repo.vector_count(source="semantic") == 2
    assert await repo.vector_count(source="episodic") == 1
    await repo.close()


async def test_backfill_is_idempotent(tmp_path: Path, embedder: FakeEmbedder) -> None:
    # Arrange
    db_path = tmp_path / "bob.db"
    legacy = SqliteMemoryRepo(db_path)
    await legacy.initialize()
    await legacy.save_fact(_fact("bob loves jazz"))
    await legacy.close()

    # Act: initialize twice with an embedder; the second run must skip embedded rows.
    first = SqliteMemoryRepo(db_path, embedder=embedder)
    await first.initialize()
    await first.close()
    second = SqliteMemoryRepo(db_path, embedder=embedder)
    await second.initialize()

    # Assert: still exactly one vector (no duplicates).
    assert await second.vector_count(source="semantic") == 1
    await second.close()


async def test_dimension_mismatch_is_rejected(tmp_path: Path) -> None:
    # Arrange: an embedder whose dimension disagrees with the schema's float[1024].
    bad = FakeEmbedder(dim=_DIM // 2)
    repo = SqliteMemoryRepo(tmp_path / "bob.db", embedder=bad)
    await repo.initialize()

    # Act / Assert: inserting a wrong-width vector must raise (dimension enforced).
    with pytest.raises(sqlite3.OperationalError, match=r"[Dd]imension"):
        await repo.save_fact(_fact("bob loves jazz"))
    await repo.close()
