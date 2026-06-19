# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Fts5MemoryRecall — keyword relevance retrieval over the whole archive.

Realises :class:`bob.domain.ports.MemoryRecall` in P0 using SQLite's FTS5
``MATCH`` with BM25 ranking. Recall spans both distilled semantic facts *and*
the raw episodic conversation archive (Fix A): an old turn that was never
fact-extracted is still surfaced, so Bob can recall something said many turns
ago. Hits from both indexes are merged, deduplicated, ranked by BM25 and
truncated to the top ``k``; each item carries a ``source`` tag (``semantic`` /
``episodic``). The port is the seam for a future vector store: the domain only
sees ``recall(query, k) -> [Recalled]`` and never learns it is keyword-backed.
Raw user text is sanitised into a safe FTS5 query so operator characters can
never raise a syntax error or be injected.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.domain.ports import Recalled
    from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

# FTS5 tokens: keep word characters, drop operator punctuation entirely.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Fts5MemoryRecall:
    """Top-``k`` keyword recall over the semantic + episodic FTS5 indexes."""

    def __init__(self, repo: SqliteMemoryRepo) -> None:
        self._repo = repo

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:
        """Return up to ``k`` archive memories matching ``query`` (best first).

        Searches semantic facts and the episodic conversation archive, merges
        the hits, drops duplicate content, ranks by BM25 (lower is better) and
        returns the top ``k``.
        """
        match_expr = _to_match_query(query)
        if not match_expr or k <= 0:
            return []
        merged = [
            *await self._semantic_hits(match_expr, k),
            *await self._episodic_hits(match_expr, k),
        ]
        merged.sort(key=_score)
        return _dedup_by_content(merged)[:k]

    async def _semantic_hits(self, match_expr: str, k: int) -> list[dict[str, object]]:
        """Top-``k`` distilled semantic facts matching ``match_expr``."""
        async with self._repo.connection.execute(
            "SELECT sm.content AS content, sm.category AS category, "
            "bm25(semantic_fts) AS score, 'semantic' AS source "
            "FROM semantic_fts "
            "JOIN semantic_memory sm ON sm.id = semantic_fts.rowid "
            "WHERE semantic_fts MATCH ? "
            "ORDER BY score LIMIT ?",
            (match_expr, k),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _episodic_hits(self, match_expr: str, k: int) -> list[dict[str, object]]:
        """Top-``k`` raw episodic-archive turns matching ``match_expr``."""
        async with self._repo.connection.execute(
            "SELECT el.content AS content, el.event_type AS category, "
            "bm25(episodic_fts) AS score, 'episodic' AS source "
            "FROM episodic_fts "
            "JOIN episodic_log el ON el.id = episodic_fts.rowid "
            "WHERE episodic_fts MATCH ? "
            "ORDER BY score LIMIT ?",
            (match_expr, k),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def _score(hit: dict[str, object]) -> float:
    """BM25 relevance of a hit (lower is better); coerced from the SQL row."""
    return float(str(hit["score"]))


def _dedup_by_content(hits: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop later hits whose content was already seen (best-ranked wins)."""
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for hit in hits:
        content = str(hit["content"])
        if content in seen:
            continue
        seen.add(content)
        unique.append(hit)
    return unique


def _to_match_query(query: str) -> str:
    """Turn raw user text into a safe FTS5 OR-of-quoted-terms expression."""
    terms = _TOKEN_RE.findall(query)
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms)
