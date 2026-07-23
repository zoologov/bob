# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=application

"""DedupFacts — the rare, conservative fact-merge step (BOB-021).

Hooked onto the heartbeat reflect tick (a slow cadence), this lets Bob's semantic
memory stay clean without ever forgetting. Over time fact extraction accumulates
near-duplicates — "любит зелёный чай" / "обожает зелёный чай" — that clutter recall.
Each run:

1. **Select ACTIVE facts** — every fact not already merged (``superseded_by IS
   NULL``), capped by a config batch. Already-superseded facts are excluded, so a
   re-run with nothing new to merge is a clean no-op (idempotent).
2. **Embed locally** — one batch through the injected :class:`~bob.domain.ports.Embedder`
   (privacy: memory content never leaves the machine; in tests a fake).
3. **Cluster by cosine** — single-linkage clustering of facts whose pairwise cosine
   similarity is **at or above a CONSERVATIVE threshold** (``memory.dedup.threshold``,
   default ~0.92). Dissimilar facts stay in their own singleton cluster and are NEVER
   merged — the high threshold guards against false merges.
4. **Pick a canonical & supersede** — for each cluster of two or more, the canonical
   is the **newest** fact (ties broken by **longest** content, then smallest id — the
   most complete, stable phrasing); every other fact in the cluster is flagged
   ``superseded_by`` the canonical.

**Non-destructive:** superseded rows are kept with provenance (the canonical id), only
excluded from recall. **Bounded & gated:** the batch size comes from config (zero
disables the step); off by default like consolidation. Everything is injected — store,
embedder, clock — so the step holds no globals and is deterministic on fakes.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.domain.ports import Clock, Embedder

logger = logging.getLogger(__name__)

# Conservative default cosine threshold (overridable via ``memory.dedup.threshold``):
# only facts this near in embedding space are treated as the same fact. High on
# purpose — a false merge silently loses a distinct memory, so the bar is strict.
_DEFAULT_THRESHOLD = 0.92

# Default per-run cap on how many active facts a single rare tick considers.
_DEFAULT_BATCH_SIZE = 200


class DedupStore(Protocol):
    """The persistence seam DedupFacts drives (BOB-021).

    Realised by :class:`~bob.infrastructure.persistence.sqlite_repo.SqliteMemoryRepo`:
    select ACTIVE (un-superseded) facts and flag near-duplicates as superseded into a
    canonical fact — non-destructively (the rows stay, with provenance).
    """

    async def select_active_facts(self) -> Sequence[Mapping[str, object]]:
        """Return every ACTIVE (un-superseded) semantic fact (id, ts, content)."""
        ...

    async def supersede_facts(self, mapping: Mapping[int, int]) -> None:
        """Flag ``{duplicate_id: canonical_id}`` duplicates as superseded (non-destructive)."""
        ...


class DedupFacts:
    """Rarely merge near-duplicate facts — conservative, non-destructive, idempotent."""

    def __init__(
        self,
        *,
        store: DedupStore,
        embedder: Embedder,
        clock: Clock,
        threshold: float = _DEFAULT_THRESHOLD,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._clock = clock
        # Clamp to a sane cosine range; a threshold of 1.0 merges only identical
        # vectors (maximally conservative).
        self._threshold = min(1.0, max(0.0, threshold))
        self._batch_size = max(0, batch_size)

    async def run(self) -> None:
        """Run one dedup step: merge near-duplicate facts (or a clean no-op)."""
        if self._batch_size == 0:
            return
        facts = list(await self._store.select_active_facts())[: self._batch_size]
        if len(facts) < 2:  # noqa: PLR2004 — nothing can duplicate a lone fact.
            return  # nothing to compare: a clean, idempotent no-op.
        vectors = await self._embedder.embed([str(f["content"]) for f in facts])
        if len(vectors) != len(facts):
            logger.debug("dedup: embedder returned a misaligned batch; skipping")
            return
        mapping = _supersession_mapping(facts, vectors, self._threshold)
        if not mapping:
            return  # no near-duplicates above threshold: idempotent no-op.
        await self._store.supersede_facts(mapping)
        logger.debug("dedup merged %d near-duplicate fact(s)", len(mapping))


def _supersession_mapping(
    facts: Sequence[Mapping[str, object]],
    vectors: Sequence[Sequence[float]],
    threshold: float,
) -> dict[int, int]:
    """Build ``{duplicate_id: canonical_id}`` for every near-duplicate cluster.

    Facts are clustered single-linkage by cosine similarity at or above
    ``threshold``; each cluster of two or more contributes a canonical (the newest,
    then longest, then smallest-id fact) and maps its other members onto it.
    """
    clusters = _cluster(vectors, threshold)
    mapping: dict[int, int] = {}
    for members in clusters:
        if len(members) < 2:  # noqa: PLR2004 — singletons have no duplicate.
            continue
        canonical = _canonical(facts, members)
        canonical_id = int(str(facts[canonical]["id"]))
        for index in members:
            if index == canonical:
                continue
            mapping[int(str(facts[index]["id"]))] = canonical_id
    return mapping


def _cluster(vectors: Sequence[Sequence[float]], threshold: float) -> list[list[int]]:
    """Single-linkage clusters of vector indices linked by cosine >= ``threshold``.

    Union-find over every pair: two facts join the same cluster if their cosine
    similarity meets the threshold, and the relation chains transitively (A~B, B~C
    -> {A, B, C}). Returns one index list per cluster.
    """
    parent = list(range(len(vectors)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            if _cosine(vectors[i], vectors[j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for index in range(len(vectors)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def _canonical(facts: Sequence[Mapping[str, object]], members: Sequence[int]) -> int:
    """Pick the canonical member of a cluster: newest, then longest, then smallest id.

    The canonical is the fact we keep: the most recent (freshest phrasing), breaking
    ties on the longest content (the most complete) and finally the smallest id (a
    stable, deterministic tiebreak).
    """
    return max(
        members,
        key=lambda index: (
            str(facts[index]["ts"]),
            len(str(facts[index]["content"])),
            -int(str(facts[index]["id"])),
        ),
    )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (0.0 when either has zero magnitude)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
