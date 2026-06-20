# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Persistence adapters — SQLite memory store, FTS5 recall, and SoulStore.

Realises the domain's storage ports (:class:`bob.domain.ports.MemoryRepo`,
:class:`bob.domain.ports.MemoryRecall`). All SQL and filesystem I/O for Bob's
durable state live here; the schema is bundled as ``schema.sql``.
"""

from __future__ import annotations

from bob.infrastructure.persistence.allowlist_store import KvAllowlistStore
from bob.infrastructure.persistence.fts_recall import Fts5MemoryRecall
from bob.infrastructure.persistence.hybrid_recall import HybridMemoryRecall
from bob.infrastructure.persistence.proactivity_sources import RepoProactivitySources
from bob.infrastructure.persistence.proactivity_store import SqliteProactivityStore
from bob.infrastructure.persistence.soul_store import SoulStore
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

__all__ = [
    "Fts5MemoryRecall",
    "HybridMemoryRecall",
    "KvAllowlistStore",
    "RepoProactivitySources",
    "SoulStore",
    "SqliteMemoryRepo",
    "SqliteProactivityStore",
]
