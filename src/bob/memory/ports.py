# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Memory ports — persistence, the autobiography recorder, and the semantic seams.

The durable episode/fact store (:class:`MemoryRepo`), the self-action recorder
(:class:`SelfActionRecorder`), and the additive semantic-memory seams
(:class:`Embedder`, :class:`Reranker`). Relevance recall
(:class:`~bob.kernel.ports.MemoryRecall`) and the item it returns
(:data:`~bob.kernel.episode_types.Recalled`) live in the shared kernel (BOB-113): they
are read below ``memory``. These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the SQLite/FTS5 and
Ollama-backed adapters live in ``bob.infrastructure``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.kernel.episode_types import Recalled
    from bob.memory.entities import SemanticFact
    from bob.memory.self_action import SelfAction


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
class SelfActionRecorder(Protocol):
    """Узкий порт записи самодействия Боба в автобиографию (BOB-079).

    Намеренно НЕ весь :class:`MemoryRepo`: coding-сессия и tool-loop получают ровно
    одну способность — «записать поступок» — а не полный доступ к памяти. Реализация
    рендерит :class:`~bob.memory.self_action.SelfAction` от первого лица и оседает
    эпизодом ``self_action``; no-op-реализация решает выключенный флаг
    ``memory.autobiography`` (запись отсутствует, поведение как раньше). Best-effort у
    вызывающего: провал записи не должен ронять coding/приём (урок Part D BOB-078).
    """

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        """Записать один поступок Боба (или тихо ничего — no-op при OFF-флаге)."""
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

    Sits *on top of* :class:`~bob.kernel.ports.MemoryRecall`: the hybrid recall
    surfaces a wide top-``K`` pool (RRF over keyword + vector), and the reranker re-orders that
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
