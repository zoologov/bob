# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Memory ports — persistence, relevance retrieval, and the semantic seams.

The durable episode/fact store (:class:`MemoryRepo`), relevance recall
(:class:`MemoryRecall`), and the additive semantic-memory seams
(:class:`Embedder`, :class:`Reranker`). These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the SQLite/FTS5 and
Ollama-backed adapters live in ``bob.infrastructure``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.memory.entities import SemanticFact

# A single recalled memory item (content + relevance score), returned by recall.
type Recalled = Mapping[str, object]


@runtime_checkable
class MemoryRepo(Protocol):
    """Persistent store for episodes, facts, and personality state (SQLite)."""

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        """Append one episodic event to durable storage."""
        ...

    async def save_fact(self, fact: SemanticFact) -> None:
        """Persist one durable semantic fact (the FTS index is updated too)."""
        ...

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` most-recent episodes (newest first)."""
        ...

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        """Return the last ``k`` episodes by recency, in chronological order.

        Oldest-first within the window so callers can replay recent conversation
        history into a reply prompt; a non-positive ``k`` yields an empty sequence.
        """
        ...


@runtime_checkable
class MemoryRecall(Protocol):
    """Relevance retrieval over memory (P0: FTS5 keyword; seam for vectors)."""

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        """Return the top-``k`` memories relevant to ``query``.

        ``surface_old`` is an ADDITIVE opt-in (BOB-021 mechanism 1): when set, an
        implementation MAY blend ONE old-but-relevant memory into the result (relevant
        by embedding, biased toward an older timestamp) so a deep cut can surface that
        recency ordering would otherwise drop. It defaults off — the default call is a
        drop-in, unchanged contract — and an implementation with no age signal
        (keyword-only) treats it as a graceful no-op.
        """
        ...


@runtime_checkable
class Embedder(Protocol):
    """Maps texts to dense embedding vectors (the semantic-memory seam).

    Provider-agnostic by design: an Ollama-backed adapter (BGE-M3, 1024-dim) is
    the first realisation, but the port commits only to "text in, one vector per
    text out" so a later local model (e.g. Qwen3-Embedding) swaps in without any
    consumer change. Embeddings stay local for privacy — memory content never
    leaves the machine. The vector dimension is fixed by the configured model.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` into one dense vector each (order-preserving).

        Returns a list aligned with ``texts``: element ``i`` is the embedding of
        ``texts[i]``. Every vector shares the model's fixed dimension. An empty
        input yields an empty list.
        """
        ...


@runtime_checkable
class Reranker(Protocol):
    """Re-scores recall candidates by relevance (an additive quality boost).

    Sits *on top of* :class:`MemoryRecall`: the hybrid recall surfaces a wide
    top-``K`` pool (RRF over keyword + vector), and the reranker re-orders that
    pool by a sharper relevance judgement and trims it to a tight top-``N``. It is
    deliberately ADDITIVE — a recall that cannot reach a reranker (disabled, model
    absent, endpoint down) returns the hybrid order unchanged, so reranking never
    regresses retrieval. Provider-agnostic by design: the first realisation is an
    Ollama-as-scorer (there is no native rerank endpoint — Q1), but the port
    commits only to "query + candidates in, re-ordered (trimmed) candidates out",
    so a dedicated local rerank service swaps in without any consumer change.
    Like embeddings, it runs locally — memory content never leaves the machine.
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[Recalled],
    ) -> list[Recalled]:
        """Return ``candidates`` re-ordered by relevance to ``query`` (best first).

        The result is optionally trimmed to the adapter's configured top-``N``.
        Implementations MUST degrade gracefully: on any unavailability or scoring
        failure they return the input ``candidates`` unchanged (never raise into
        the caller). An empty input yields an empty list.
        """
        ...
