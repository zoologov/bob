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
from bob.infrastructure.persistence.fts_recall import Fts5MemoryRecall
from bob.infrastructure.persistence.hybrid_recall import HybridMemoryRecall
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
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


async def test_hybrid_beats_pure_keyword_on_a_no_overlap_query(tmp_path: Path) -> None:
    # US-1 acceptance, made explicit as a SIDE-BY-SIDE: a query semantically near a
    # fact but with ZERO shared words is MISSED by pure keyword FTS5 yet FOUND by the
    # hybrid (its vector half bridges meaning). One db, two recall strategies.
    query = "feline companion"
    target = "bob adores his cat whiskers"  # no word overlap with the query
    embedder = StubEmbedder({query: _unit(0), target: _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact(target))

    keyword_only = [str(r["content"]) for r in await Fts5MemoryRecall(db).recall(query, k=5)]
    hybrid = [str(r["content"]) for r in await HybridMemoryRecall(db, embedder).recall(query, k=5)]

    # Assert: keyword recall misses the meaning-only match; the hybrid surfaces it.
    assert target not in keyword_only  # pure FTS5 cannot bridge the synonym gap
    assert target in hybrid  # the hybrid's vector half does
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


class _EmptyEmbedder:
    """Embedder that succeeds but returns NO vectors (e.g. an empty model reply).

    Distinct from a raising embedder: the call does not fault, it just yields an
    empty list, so hybrid recall must still degrade to keyword-only rather than
    index ``vectors[0]`` and crash.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:  # noqa: ARG002
        self.calls += 1
        return []


async def test_empty_embedding_result_degrades_to_keyword(tmp_path: Path) -> None:
    # Embedder returns an empty list (no fault, but no vector either) -> there is no
    # query vector to KNN with, so recall degrades to pure keyword without crashing.
    write_embedder = StubEmbedder({"bob loves jazz": _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=write_embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))

    empty = _EmptyEmbedder()
    recall = HybridMemoryRecall(db, empty)
    results = await recall.recall("jazz", k=5)

    assert any("jazz" in str(r["content"]) for r in results)  # keyword carried it
    assert empty.calls == 1  # it tried the semantic half, got nothing, fell back
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


# --- Reranker integration (BEAD-04) -------------------------------------------
#
# The reranker is an ADDITIVE quality boost: hybrid recall surfaces a wide top-K
# pool, the reranker re-orders it and trims to top-N. It must never regress recall
# — a disabled/None/failing reranker yields the hybrid order unchanged. A FAKE
# reranker (no network) drives the wiring deterministically.


class FakeReranker:
    """Reranker that re-scores by an explicit content->score table, trims to top_n.

    Realises :class:`bob.domain.ports.Reranker`. Higher score ranks first; unknown
    content scores 0.0. Set ``fail`` to simulate an unavailable reranker — per the
    additive contract it then returns the input candidates unchanged (never raises).
    """

    def __init__(
        self,
        scores: dict[str, float],
        *,
        top_n: int,
        fail: bool = False,
    ) -> None:
        self._scores = scores
        self._top_n = top_n
        self.fail = fail
        self.calls = 0

    async def rerank(
        self, query: str, candidates: Sequence[Mapping[str, object]]
    ) -> list[Mapping[str, object]]:
        del query  # this fake ranks by a content->score table, ignoring the query
        self.calls += 1
        items = list(candidates)
        if self.fail:
            return items  # graceful: keep hybrid order, never crash recall
        ranked = sorted(
            items,
            key=lambda hit: -self._scores.get(str(hit["content"]), 0.0),
        )
        return ranked[: self._top_n]


async def test_reranker_reorders_hybrid_candidates_to_top_n(tmp_path: Path) -> None:
    # The reranker re-scores the hybrid pool by a known key: the candidate it
    # scores highest is promoted to the front, and the list is trimmed to top_n.
    query = "jazz"
    embedder = StubEmbedder(
        {
            query: _unit(0),
            "bob loves jazz": _unit(0),
            "smooth saxophone evenings": _unit(0),
            "late night blue notes": _unit(0),
        }
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))
    await db.save_fact(_fact("smooth saxophone evenings"))
    await db.save_fact(_fact("late night blue notes"))

    # Reranker prefers the vector-only candidate that keyword fusion ranked lower.
    reranker = FakeReranker(
        {"smooth saxophone evenings": 0.9, "bob loves jazz": 0.5, "late night blue notes": 0.1},
        top_n=2,
    )
    recall = HybridMemoryRecall(db, embedder, reranker=reranker)
    results = await recall.recall(query, k=5)

    contents = [str(r["content"]) for r in results]
    assert contents == ["smooth saxophone evenings", "bob loves jazz"]  # reordered + trimmed
    assert reranker.calls == 1
    await db.close()


async def test_no_reranker_returns_hybrid_order_unchanged(tmp_path: Path) -> None:
    # With no reranker wired, recall == the BEAD-03 hybrid result (drop-in).
    query = "jazz"
    embedder = StubEmbedder({query: _unit(0), "bob loves jazz": _unit(0)})
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))

    hybrid = await HybridMemoryRecall(db, embedder).recall(query, k=5)
    with_none = await HybridMemoryRecall(db, embedder, reranker=None).recall(query, k=5)

    assert [str(r["content"]) for r in with_none] == [str(r["content"]) for r in hybrid]
    await db.close()


async def test_failing_reranker_falls_back_to_hybrid_order(tmp_path: Path) -> None:
    # The reranker is unavailable (raises/returns input): recall must NOT crash and
    # must return the hybrid order — reranking is additive, never a regression.
    query = "jazz"
    embedder = StubEmbedder(
        {query: _unit(0), "bob loves jazz": _unit(0), "smooth saxophone evenings": _unit(0)}
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))
    await db.save_fact(_fact("smooth saxophone evenings"))

    hybrid = await HybridMemoryRecall(db, embedder).recall(query, k=5)
    failing = FakeReranker({}, top_n=5, fail=True)
    results = await HybridMemoryRecall(db, embedder, reranker=failing).recall(query, k=5)

    assert [str(r["content"]) for r in results] == [str(r["content"]) for r in hybrid]
    assert failing.calls == 1  # it was consulted, then fell back
    await db.close()


async def test_reranker_runs_after_keyword_only_fallback(tmp_path: Path) -> None:
    # Even when the embedder is down (pure-FTS5 fallback), the reranker still gets
    # to re-score the keyword pool: the boost is independent of the semantic half.
    query = "jazz"
    write_embedder = StubEmbedder(
        {"bob loves jazz": _unit(0), "jazz festival tonight": _unit(0)}
    )
    db = SqliteMemoryRepo(tmp_path / "bob.db", embedder=write_embedder)
    await db.initialize()
    await db.save_fact(_fact("bob loves jazz"))
    await db.save_fact(_fact("jazz festival tonight"))

    failing_embedder = StubEmbedder({}, fail=True)  # recall's embedder is down
    reranker = FakeReranker(
        {"jazz festival tonight": 0.9, "bob loves jazz": 0.2}, top_n=2
    )
    recall = HybridMemoryRecall(db, failing_embedder, reranker=reranker)
    results = await recall.recall(query, k=5)

    contents = [str(r["content"]) for r in results]
    assert contents[0] == "jazz festival tonight"  # reranked atop keyword-only pool
    assert reranker.calls == 1
    await db.close()
