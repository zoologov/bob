# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root memory wiring — consolidation / dedup steps + embedder / reranker.

Builds the optional reflect-tick memory steps (:class:`ConsolidateMemory` /
:class:`DedupFacts`, both off by default) and the graceful-degradation embedder / reranker
(a missing/invalid section yields ``None`` — keyword-only recall — never a failed boot).
Part of the ``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.memory.adapters import build_embedder, build_reranker
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.dedup_facts import DedupFacts
from bob.runtime.config import (
    _CONSOLIDATION_BATCH_SIZE,
    _CONSOLIDATION_MAX_AGE_DAYS,
    _DEDUP_BATCH_SIZE,
    _DEDUP_THRESHOLD,
    _flag,
    _float_or,
    _int,
    _section,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.kernel.ports import Clock
    from bob.memory.adapters import SqliteMemoryRepo
    from bob.memory.ports import Embedder, Reranker

logger = logging.getLogger(__name__)


def _build_consolidate_memory(
    config: Mapping[str, object],
    *,
    store: SqliteMemoryRepo,
    router: LLMRouter,
    clock: Clock,
    language: str,
) -> ConsolidateMemory | None:
    """Build the optional BOB-021 :class:`ConsolidateMemory`, or ``None`` when off.

    Reads ``memory.consolidation.*``: ``enabled`` (off by default — the step stays
    inert until deliberately switched on), ``max_age_days`` and ``batch_size`` (the
    conservative age/batch guardrails). When disabled, the reflect tick gets no
    consolidator and behaves exactly as before. ``SqliteMemoryRepo`` structurally
    satisfies the use-case's ``ConsolidationStore`` seam.
    """
    section = _section(_section(config, "memory"), "consolidation")
    if not _flag(section, "enabled"):
        return None
    return ConsolidateMemory(
        store=store,
        router=router,
        clock=clock,
        max_age_days=_float_or(section, "max_age_days", _CONSOLIDATION_MAX_AGE_DAYS),
        batch_size=_int(section, "batch_size", _CONSOLIDATION_BATCH_SIZE),
        language=language,
    )


def _build_dedup_facts(
    config: Mapping[str, object],
    *,
    store: SqliteMemoryRepo,
    embedder: Embedder | None,
    clock: Clock,
) -> DedupFacts | None:
    """Build the optional BOB-021 :class:`DedupFacts`, or ``None`` when off.

    Reads ``memory.dedup.*``: ``enabled`` (off by default — the step stays inert until
    deliberately switched on), ``threshold`` (the conservative cosine bar) and
    ``batch_size``. Returns ``None`` when disabled OR when there is no embedder
    (keyword-only memory cannot compute cosine), so the reflect tick gets no deduper and
    behaves exactly as before. ``SqliteMemoryRepo`` structurally satisfies the
    use-case's ``DedupStore`` seam.
    """
    section = _section(_section(config, "memory"), "dedup")
    if not _flag(section, "enabled") or embedder is None:
        return None
    return DedupFacts(
        store=store,
        embedder=embedder,
        clock=clock,
        threshold=_float_or(section, "threshold", _DEDUP_THRESHOLD),
        batch_size=_int(section, "batch_size", _DEDUP_BATCH_SIZE),
    )


def _build_embedder(config: Mapping[str, object]) -> Embedder | None:
    """Build the local :class:`Embedder` from ``embeddings.*``, or ``None``.

    Graceful degradation: a missing/invalid ``embeddings`` section is logged and
    yields ``None`` (keyword-only recall) rather than failing the whole boot —
    building the embedder never touches the network, so this only guards config
    shape. An embedder that later fails at runtime (Ollama down) is handled inside
    the hybrid recall, not here.
    """
    try:
        return build_embedder(config)
    except (KeyError, ValueError) as error:
        logger.warning(
            "embeddings not configured (%s); memory recall degrades to keyword-only",
            error,
        )
        return None


def _build_reranker(config: Mapping[str, object]) -> Reranker | None:
    """Build the optional :class:`Reranker` from ``reranker.*``, or ``None``.

    The reranker is an ADDITIVE boost: it is off by default (``reranker.enabled``
    false) and a missing/invalid section degrades to ``None`` (the hybrid order
    ships unchanged) rather than failing the boot.
    """
    try:
        return build_reranker(config)
    except (KeyError, ValueError) as error:
        logger.warning("reranker not configured (%s); using hybrid order", error)
        return None
