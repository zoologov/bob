# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Fts5MemoryRecall — keyword relevance retrieval over semantic memory.

Realises :class:`bob.domain.ports.MemoryRecall` in P0 using SQLite's FTS5
``MATCH`` with BM25 ranking. The port is the seam for a future vector store: the
domain only sees ``recall(query, k) -> [Recalled]`` and never learns it is
keyword-backed. Raw user text is sanitised into a safe FTS5 query so operator
characters can never raise a syntax error or be injected.
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
    """Top-``k`` keyword recall over ``semantic_memory`` via the FTS5 index."""

    def __init__(self, repo: SqliteMemoryRepo) -> None:
        self._repo = repo

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:
        """Return up to ``k`` semantic memories matching ``query`` (best first)."""
        match_expr = _to_match_query(query)
        if not match_expr:
            return []
        async with self._repo.connection.execute(
            "SELECT sm.content AS content, sm.category AS category, "
            "bm25(semantic_fts) AS score "
            "FROM semantic_fts "
            "JOIN semantic_memory sm ON sm.id = semantic_fts.rowid "
            "WHERE semantic_fts MATCH ? "
            "ORDER BY score LIMIT ?",
            (match_expr, k),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def _to_match_query(query: str) -> str:
    """Turn raw user text into a safe FTS5 OR-of-quoted-terms expression."""
    terms = _TOKEN_RE.findall(query)
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms)
