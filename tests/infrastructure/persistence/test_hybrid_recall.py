# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for HybridMemoryRecall: FTS5(BM25) + sqlite-vec(KNN) fused with RRF.

Drives BEAD-03: a drop-in :class:`~bob.domain.ports.MemoryRecall` that fuses a
semantic (vector KNN) candidate list with a keyword (FTS5 BM25) candidate list
via Reciprocal Rank Fusion. The key win is "помнит по смыслу" — a query with no
keyword overlap still surfaces semantically-near memory through the vector half.
No network: a controllable in-test :class:`StubEmbedder` provides deterministic
vectors so cosine-near pairs and embedder failures are both reproducible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.memory.entities import SemanticFact
from bob.infrastructure.persistence.hybrid_recall import HybridMemoryRecall
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# The schema fixes embeddings at BGE-M3's 1024 dims, so test vectors match it.
_DIM = 1024


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


def _fact(content: str) -> SemanticFact:
    return SemanticFact(ts=_ts(), category="pref", content=content)


class StubEmbedder:
    """Deterministic embedder driven by an explicit text->vector table.

    Realises :class:`bob.domain.ports.Embedder`. Any text not in the table maps
    to a fixed orthogonal-ish default so unrelated content stays far in cosine
    space. Set ``fail`` to simulate an unavailable Ollama (the embed call raises).
    """

    def __init__(self, table: dict[str, list[float]], *, fail: bool = False) -> None:
        self._table = table
        self.fail = fail
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            msg = "embedder unavailable (Ollama down)"
            raise RuntimeError(msg)
        return [self._table.get(text, self._default()) for text in texts]

    @staticmethod
    def _default() -> list[float]:
        vec = [0.0] * _DIM
        vec[_DIM - 1] = 1.0
        return vec


def _unit(*axes: int) -> list[float]:
    """A unit vector with 1.0 on the given axis (e.g. ``_unit(0)`` -> e0)."""
    vec = [0.0] * _DIM
    for axis in axes:
        vec[axis] = 1.0
    return vec


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    return SqliteMemoryRepo(tmp_path / "bob.db")


async def test_semantic_hit_without_keyword_overlap(tmp_path: Path) -> None:
    # The key win: a query semantically near a fact but with ZERO shared words
    # is still recalled — via the vector half. Keyword FTS5 alone would miss it.
    query = "feline companion"
    target = "bob adores his cat whiskers"
    # Make query and target share the same embedding axis (cosine ~ 1), and an
    # unrelated fact land on a different axis (cosine ~ 0).
    embedder = StubEmbedder(
        {
            query: _unit(0),
            target: _unit(0),
            "the weather is rainy today": _unit(3),
        }
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact(target))
    await db.save_fact(_fact("the weather is rainy today"))

    recall = HybridMemoryRecall(db, embedder)
    results = await recall.recall(query, k=5)

    contents = [str(r["content"]) for r in results]
    assert target in contents  # found purely by meaning, no shared keyword
    await db.close()


async def test_rrf_ranks_item_in_both_lists_higher(tmp_path: Path) -> None:
    # An item present in BOTH the keyword list and the vector list must outrank
    # an item present in only one — that is the whole point of rank fusion.
    query = "jazz"
    both = "bob loves jazz"  # matches keyword 'jazz' AND is vector-near
    vector_only = "smooth saxophone evenings"  # only vector-near, no keyword
    embedder = StubEmbedder(
        {
            query: _unit(0),
            both: _unit(0),
            vector_only: _unit(0),
            "the sky is blue": _unit(5),
        }
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact(both))
    await db.save_fact(_fact(vector_only))
    await db.save_fact(_fact("the sky is blue"))

    recall = HybridMemoryRecall(db, embedder)
    results = await recall.recall(query, k=5)

    contents = [str(r["content"]) for r in results]
    assert contents[0] == both  # in both lists -> highest RRF score
    assert vector_only in contents
    await db.close()


async def test_results_are_deduplicated(tmp_path: Path) -> None:
    # A fact that is BOTH a keyword hit and a vector hit must appear exactly once.
    query = "jazz"
    fact = "bob loves jazz"
    embedder = StubEmbedder({query: _unit(0), fact: _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact(fact))

    recall = HybridMemoryRecall(db, embedder)
    results = await recall.recall(query, k=5)

    contents = [str(r["content"]) for r in results]
    assert contents.count(fact) == 1
    await db.close()


async def test_fallback_to_keyword_when_embedder_fails(tmp_path: Path) -> None:
    # Embedder raises at recall time (Ollama down) -> degrade to pure FTS5
    # keyword recall. Bob never "loses his memory"; he loses the semantic half.
    # The archive was written with a healthy embedder; only recall's embedder dies.
    write_embedder = StubEmbedder({"bob loves jazz": _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=write_embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))

    failing = StubEmbedder({}, fail=True)
    recall = HybridMemoryRecall(db, failing)
    results = await recall.recall("jazz", k=5)

    contents = [str(r["content"]) for r in results]
    assert any("jazz" in c for c in contents)  # still recalled by keyword
    assert failing.calls == 1  # it tried the semantic half, then fell back
    await db.close()


async def test_no_embedder_is_pure_keyword(tmp_path: Path) -> None:
    # With no embedder wired at all, hybrid recall == keyword recall (no crash).
    db = SqliteMemoryRepo(tmp_path / "bob.db")
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))

    recall = HybridMemoryRecall(db, embedder=None)
    results = await recall.recall("jazz", k=5)

    assert any("jazz" in str(r["content"]) for r in results)
    await db.close()


async def test_results_tagged_with_source(tmp_path: Path) -> None:
    # Each fused item keeps a source tag so callers can tell facts from episodes.
    query = "jazz"
    fact = "bob loves jazz"
    embedder = StubEmbedder({query: _unit(0), fact: _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact(fact))

    recall = HybridMemoryRecall(db, embedder)
    results = await recall.recall(query, k=5)

    assert results
    assert all("source" in r for r in results)
    assert all(r["source"] in {"semantic", "episodic"} for r in results)
    await db.close()


async def test_recall_is_deterministic(tmp_path: Path) -> None:
    # Fixed fake vectors -> stable fused ordering across repeated calls.
    query = "jazz"
    embedder = StubEmbedder(
        {
            query: _unit(0),
            "bob loves jazz": _unit(0),
            "smooth saxophone evenings": _unit(0, 1),
            "the sky is blue": _unit(5),
        }
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))
    await db.save_fact(_fact("smooth saxophone evenings"))
    await db.save_fact(_fact("the sky is blue"))
    recall = HybridMemoryRecall(db, embedder)

    first = [str(r["content"]) for r in await recall.recall(query, k=5)]
    second = [str(r["content"]) for r in await recall.recall(query, k=5)]

    assert first == second
    await db.close()


async def test_empty_query_returns_empty(tmp_path: Path) -> None:
    embedder = StubEmbedder({})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))

    recall = HybridMemoryRecall(db, embedder)

    assert await recall.recall("   ", k=5) == []
    assert await recall.recall("jazz", k=0) == []
    await db.close()
