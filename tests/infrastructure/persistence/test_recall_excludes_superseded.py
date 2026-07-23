# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Recall must exclude superseded facts (BOB-021 dedup).

A near-duplicate fact merged into a canonical one (``superseded_by`` set) is kept
in the archive (non-destructive) but must NOT resurface in recall — otherwise the
merge would be pointless. Both retrieval halves filter it out: FTS5 keyword recall
and the sqlite-vec semantic KNN. The ``MemoryRecall`` contract is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.hybrid_recall import HybridMemoryRecall
from bob.memory.entities import SemanticFact

if TYPE_CHECKING:
    from pathlib import Path

from tests.support.fake_embedder import FakeEmbedder


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


def _fact(content: str) -> SemanticFact:
    return SemanticFact(ts=_ts(), category="user", content=content)


async def _supersede(repo: SqliteMemoryRepo, *, duplicate: str, canonical: str) -> None:
    """Mark the fact whose content is ``duplicate`` as merged into ``canonical``."""
    rows = await repo.select_active_facts()
    ids = {str(r["content"]): int(str(r["id"])) for r in rows}
    await repo.supersede_facts({ids[duplicate]: ids[canonical]})


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_fts_recall_excludes_superseded_fact(repo: SqliteMemoryRepo) -> None:
    # Arrange: a canonical fact and a near-duplicate, the duplicate superseded.
    await repo.save_fact(_fact("любит зелёный чай"))
    await repo.save_fact(_fact("обожает зелёный чай"))
    await _supersede(repo, duplicate="обожает зелёный чай", canonical="любит зелёный чай")
    recall = Fts5MemoryRecall(repo)

    # Act
    hits = await recall.recall("зелёный чай", k=10)

    # Assert: the superseded duplicate never resurfaces.
    contents = {str(h["content"]) for h in hits}
    assert "обожает зелёный чай" not in contents
    assert "любит зелёный чай" in contents
    await repo.close()


async def test_vector_recall_excludes_superseded_fact(tmp_path: Path) -> None:
    # Arrange: an embedder-backed repo so the vector half is populated.
    embedder = FakeEmbedder(dim=1024)
    repo = SqliteMemoryRepo(tmp_path / "vec.db", embedder=embedder)
    await repo.initialize()
    await repo.save_fact(_fact("canonical only fact"))
    await repo.save_fact(_fact("superseded duplicate fact"))
    await _supersede(
        repo, duplicate="superseded duplicate fact", canonical="canonical only fact"
    )
    recall = HybridMemoryRecall(repo, embedder)

    # Act: query that the vector half should answer.
    hits = await recall.recall("superseded duplicate fact", k=10)

    # Assert: the superseded fact is filtered from the semantic KNN too.
    contents = {str(h["content"]) for h in hits}
    assert "superseded duplicate fact" not in contents
    await repo.close()


async def test_active_facts_still_recalled(repo: SqliteMemoryRepo) -> None:
    # Arrange: an active fact (no supersession) recalls as before (drop-in).
    await repo.save_fact(_fact("живёт в Москве"))
    recall = Fts5MemoryRecall(repo)

    # Act
    hits = await recall.recall("Москве", k=10)

    # Assert
    assert any(str(h["content"]) == "живёт в Москве" for h in hits)
    await repo.close()
