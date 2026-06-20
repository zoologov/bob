# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""HybridMemoryRecall — semantic + keyword recall fused with Reciprocal Rank Fusion.

Realises :class:`bob.domain.ports.MemoryRecall` as a drop-in replacement for the
keyword-only :class:`Fts5MemoryRecall`: consumers (``handle_message`` /
``recall_memory``) keep talking to ``recall(query, k) -> [Recalled]`` and never
learn the retrieval grew a semantic half. Internally it runs two candidate
searches over the same archive and fuses them:

* **Semantic** — embed the query through the injected
  :class:`~bob.domain.ports.Embedder` and run a sqlite-vec KNN over ``memory_vec``
  (finds memory by *meaning*, even with zero shared keywords).
* **Keyword** — FTS5 BM25 over the semantic + episodic indexes (reuses
  :class:`Fts5MemoryRecall`).

The two ranked lists are merged with **Reciprocal Rank Fusion** (RRF score =
sum over lists of ``1 / (k0 + rank)``), deduplicated by content, and the top ``k``
returned with a ``source`` tag. An item that ranks in *both* lists accumulates a
higher fused score than one seen in only one — the point of rank fusion.

**Graceful fallback:** if the embedder is absent or raises (Ollama down), recall
degrades to pure FTS5 keyword search — Bob never "loses his memory", he just
loses the semantic half. The failure is logged, not propagated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.infrastructure.persistence.fts_recall import Fts5MemoryRecall

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.domain.ports import Embedder, Recalled
    from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

logger = logging.getLogger(__name__)

# RRF dampening constant: a small offset that flattens the contribution of top
# ranks so no single list dominates the fusion. 60 is the value from the original
# Cormack et al. RRF paper and the de-facto default.
_RRF_K0 = 60

# How many candidates to pull from each half before fusing. A wider pool than the
# requested ``k`` so the fusion has room to reorder; the final list is truncated
# back to ``k``.
_CANDIDATE_POOL = 20


class HybridMemoryRecall:
    """Top-``k`` recall fusing sqlite-vec KNN and FTS5 BM25 via RRF (drop-in)."""

    def __init__(self, repo: SqliteMemoryRepo, embedder: Embedder | None) -> None:
        self._repo = repo
        self._embedder = embedder
        self._keyword = Fts5MemoryRecall(repo)

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:
        """Return up to ``k`` memories relevant to ``query`` (best first).

        Fuses a semantic (vector) candidate list with a keyword (FTS5) list via
        RRF. Falls back to pure keyword recall when the embedder is unavailable.
        """
        if not query.strip() or k <= 0:
            return []
        keyword_hits = list(await self._keyword.recall(query, k=_CANDIDATE_POOL))
        vector_hits = await self._semantic_candidates(query)
        if not vector_hits:
            # No semantic half (no embedder, embedder failed, or empty store):
            # degrade to pure keyword recall — never lose Bob's memory.
            return keyword_hits[:k]
        fused = _fuse_rrf((vector_hits, keyword_hits))
        return fused[:k]

    async def _semantic_candidates(self, query: str) -> list[dict[str, object]]:
        """Vector-KNN candidates for ``query`` (empty on any embedder problem).

        Embeds the query and runs the sqlite-vec KNN. Any embedder failure
        (Ollama down) is caught and logged so recall can degrade to keyword-only;
        an absent embedder short-circuits to the same graceful empty result.
        """
        if self._embedder is None:
            return []
        try:
            vectors = await self._embedder.embed([query])
        except Exception:
            logger.warning(
                "embedder unavailable; degrading to keyword-only recall", exc_info=True
            )
            return []
        if not vectors:
            return []
        return await self._repo.vector_knn(vectors[0], k=_CANDIDATE_POOL)


def _fuse_rrf(
    ranked_lists: tuple[Sequence[Recalled], ...],
) -> list[Recalled]:
    """Fuse ranked candidate lists into one by Reciprocal Rank Fusion.

    Each list is assumed ordered best-first. A content's fused score is the sum
    over the lists it appears in of ``1 / (k0 + rank)`` (rank 0-based), so an item
    in several lists outranks one in a single list. The first-seen hit dict wins
    as the representative (keeping its ``source``/``category``); ties break on
    insertion order for determinism.
    """
    scores: dict[str, float] = {}
    representative: dict[str, Recalled] = {}
    order: dict[str, int] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            content = str(hit["content"])
            scores[content] = scores.get(content, 0.0) + 1.0 / (_RRF_K0 + rank)
            if content not in representative:
                representative[content] = hit
                order[content] = len(order)
    fused = sorted(
        representative,
        key=lambda content: (-scores[content], order[content]),
    )
    return [representative[content] for content in fused]
