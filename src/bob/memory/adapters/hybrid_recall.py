# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

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

**Reranker (additive boost, BEAD-04):** an optional :class:`~bob.domain.ports.Reranker`
collaborator re-scores the wide fused top-``K`` pool and trims it to a tight
top-``N`` (a sharper relevance judgement layered on top of RRF). It is strictly
additive: with no reranker wired — or one that is disabled / unavailable — recall
returns the hybrid order unchanged, so reranking never regresses retrieval. The
reranker itself owns its graceful fallback (returns its input on failure), so the
recall pipeline simply hands it the pool and uses whatever order comes back.

**surface_old (additive opt-in, BOB-021 mechanism 1 — "что-то напомнило"):** an
opt-in ``surface_old`` kwarg on :meth:`recall` blends ONE *old-but-relevant*
memory into the result — a candidate that is relevant by embedding (it sits in the
semantic KNN pool) but biased toward an OLDER ``ts`` (age-as-diversity), so a
deep-cut moment can surface that recency/RRF ordering would otherwise drop at a
tight ``k``. It is strictly additive: the default ``recall(query, k=...)`` is
**unchanged** (drop-in — the BOB-011 contract tests still pin it), the blend is a
single item (never a memory dump, the result stays bounded by ``k``), it reuses the
same superseded-filtered KNN (a deduped fact never resurfaces), and it shares the
same graceful fallback — with no embedder / one that is down there is no age signal,
so it degrades to exactly the default keyword pool. Used rarely via the BOB-018
callback path so an old moment can occasionally come back to Bob à propos.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.memory.adapters.fts_recall import Fts5MemoryRecall

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.domain.ports import Embedder, Recalled, Reranker
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

# When surface_old is requested, widen the semantic candidate pull so an OLD relevant
# memory that recency/RRF would drop at a tight ``k`` is still in reach of the age
# bias. A deeper pool than the default fusion width — the blend still adds only ONE
# item, so the wider pull just gives the age signal more deep cuts to choose from.
_SURFACE_OLD_POOL = 60


class HybridMemoryRecall:
    """Top-``k`` recall fusing sqlite-vec KNN and FTS5 BM25 via RRF (drop-in)."""

    def __init__(
        self,
        repo: SqliteMemoryRepo,
        embedder: Embedder | None,
        *,
        reranker: Reranker | None = None,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._reranker = reranker
        self._keyword = Fts5MemoryRecall(repo)

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        """Return up to ``k`` memories relevant to ``query`` (best first).

        Fuses a semantic (vector) candidate list with a keyword (FTS5) list via
        RRF, then — when a reranker is wired — re-orders the fused pool by a sharper
        relevance score. Falls back to pure keyword recall when the embedder is
        unavailable; reranking is additive and never regresses the result.

        ``surface_old`` is an ADDITIVE opt-in (BOB-021): when set, ONE old-but-relevant
        memory (relevant by embedding, biased toward an older ``ts``) is blended into
        the result so a deep cut recency/RRF would drop at this ``k`` can surface. The
        default (``surface_old=False``) is unchanged — a drop-in contract. The blend is
        a single item (the result stays bounded by ``k``) and shares the same graceful
        fallback: with no embedder / one that is down there is no age signal, so it
        degrades to exactly the default result.
        """
        if not query.strip() or k <= 0:
            return []
        pool = await self._candidate_pool(query)
        ranked = await self._rerank(query, pool)
        result = ranked[:k]
        if surface_old:
            return await self._blend_old(query, result, k=k)
        return result

    async def _candidate_pool(self, query: str) -> list[Recalled]:
        """The fused (or keyword-only) top-``K`` pool before reranking/trimming."""
        keyword_hits = list(await self._keyword.recall(query, k=_CANDIDATE_POOL))
        vector_hits = await self._semantic_candidates(query)
        if not vector_hits:
            # No semantic half (no embedder, embedder failed, or empty store):
            # degrade to pure keyword recall — never lose Bob's memory.
            return keyword_hits
        return _fuse_rrf((vector_hits, keyword_hits))

    async def _rerank(self, query: str, pool: list[Recalled]) -> list[Recalled]:
        """Re-score ``pool`` with the optional reranker (additive boost, BEAD-04).

        No reranker wired -> the hybrid order is returned unchanged. The reranker
        owns its own graceful fallback, so the pipeline trusts whatever order it
        returns; reranking never regresses retrieval.
        """
        if self._reranker is None or not pool:
            return pool
        return list(await self._reranker.rerank(query, pool))

    async def _semantic_candidates(
        self, query: str, *, k: int = _CANDIDATE_POOL
    ) -> list[dict[str, object]]:
        """Vector-KNN candidates for ``query`` (empty on any embedder problem).

        Embeds the query and runs the sqlite-vec KNN. Any embedder failure
        (Ollama down) is caught and logged so recall can degrade to keyword-only;
        an absent embedder short-circuits to the same graceful empty result. A wider
        ``k`` is requested by surface_old so the age bias has deep cuts to reach.
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
        return await self._repo.vector_knn(vectors[0], k=k)

    async def _blend_old(
        self, query: str, result: list[Recalled], *, k: int
    ) -> list[Recalled]:
        """Blend ONE old-but-relevant memory into ``result`` (surface_old, BOB-021).

        Pulls a wide superseded-filtered semantic pool (relevant by embedding),
        biases it toward the OLDEST ``ts``, and — if that deep cut is not already in
        ``result`` — slots it in within ``k`` so a moment recency/RRF dropped can
        surface. Shares the default graceful fallback: no embedder / one that is down
        yields no semantic pool, so ``result`` is returned unchanged (a clean no-op).
        The result stays bounded by ``k`` (a single blended item, never a dump).
        """
        candidates = await self._semantic_candidates(query, k=_SURFACE_OLD_POOL)
        oldest = _oldest_relevant(candidates, exclude=result)
        if oldest is None:
            return result
        # Keep within k: take the top k-1 by the existing order, then the deep cut,
        # so the old memory occupies one slot without growing the result past k.
        kept = result[: max(k - 1, 0)]
        return [*kept, oldest]


def _oldest_relevant(
    candidates: Sequence[Recalled], *, exclude: Sequence[Recalled]
) -> Recalled | None:
    """The OLDEST candidate (by ``ts``) not already in ``exclude`` (surface_old).

    Each candidate is relevant by embedding (it came from the KNN pool); biasing by
    ``ts`` ascending picks the deep cut — an old-but-relevant memory. Candidates the
    default recall already surfaced are skipped (a callback wants the OLD one, not a
    duplicate of what came back anyway). ``None`` when nothing old-and-new is left.
    Candidates without a parseable ``ts`` are treated as newest (sorted last), so a
    missing age never wins the deep-cut slot.
    """
    seen = {str(hit["content"]) for hit in exclude}
    fresh = [hit for hit in candidates if str(hit.get("content", "")) not in seen]
    if not fresh:
        return None
    return min(fresh, key=_age_key)


def _age_key(hit: Recalled) -> str:
    """Sort key biasing toward an older ``ts`` (ISO-8601 strings sort chronologically).

    A missing/blank ``ts`` sorts last (a high sentinel) so it never wins the deep-cut
    slot over a memory with a real, older timestamp.
    """
    ts = str(hit.get("ts", ""))
    return ts if ts else "9999"


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
