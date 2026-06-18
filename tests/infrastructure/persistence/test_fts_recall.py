# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the FTS5-backed keyword MemoryRecall."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.memory.entities import SemanticFact
from bob.infrastructure.persistence.fts_recall import Fts5MemoryRecall
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def populated(tmp_path: Path) -> SqliteMemoryRepo:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="bob loves jazz music"))
    await repo.save_fact(SemanticFact(ts=_ts(), category="pref", content="bob hates loud noise"))
    await repo.save_fact(SemanticFact(ts=_ts(), category="fact", content="the sky is blue today"))
    return repo


async def test_recall_finds_keyword_match(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("jazz", k=5)

    # Assert
    assert any("jazz" in str(r["content"]) for r in results)
    assert all("content" in r and "score" in r for r in results)
    await populated.close()


async def test_recall_respects_k_limit(populated: SqliteMemoryRepo) -> None:
    # Arrange: "bob" matches two facts.
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("bob", k=1)

    # Assert
    assert len(results) == 1
    await populated.close()


async def test_recall_returns_empty_on_no_match(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act
    results = await recall.recall("zzzunmatchedzzz", k=5)

    # Assert
    assert results == []
    await populated.close()


async def test_recall_handles_special_fts_characters(populated: SqliteMemoryRepo) -> None:
    # Arrange: raw user text may contain FTS5 operator characters.
    recall = Fts5MemoryRecall(populated)

    # Act / Assert: must not raise an FTS5 syntax error.
    results = await recall.recall('jazz "(music)" OR', k=5)
    assert isinstance(results, list)
    await populated.close()


async def test_recall_empty_query_returns_empty(populated: SqliteMemoryRepo) -> None:
    # Arrange
    recall = Fts5MemoryRecall(populated)

    # Act / Assert
    assert await recall.recall("   ", k=5) == []
    await populated.close()


async def test_recall_survives_a_process_restart(tmp_path: Path) -> None:
    # PRD US-3: facts must be keyword-recallable after a process restart —
    # the FTS5 index lives on disk and is not lost when the process dies.
    db_path = tmp_path / "bob.db"

    # Arrange: a first "process" persists a fact, then closes (dies).
    first = SqliteMemoryRepo(db_path)
    await first.initialize()
    await first.save_fact(
        SemanticFact(ts=_ts(), category="personal", content="user adores deep-space probes")
    )
    await first.close()

    # Act: a brand-new repo + recall over the same file simulates a restart.
    second = SqliteMemoryRepo(db_path)
    await second.initialize()
    recall = Fts5MemoryRecall(second)
    results = await recall.recall("probes", k=5)

    # Assert: the fact survived and is still recallable by keyword.
    assert any("probes" in str(r["content"]) for r in results)
    await second.close()
