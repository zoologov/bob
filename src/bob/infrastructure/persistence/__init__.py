# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Persistence adapters — the shared SQLite connection/schema kernel and SoulStore.

Home of :class:`~bob.infrastructure.persistence.connection.SqliteConnection` — the
pure-I/O connection/schema kernel (WAL, sqlite-vec load, ``schema.sql``, kv) that
every durable store reads through its ``connection`` seam — plus the filesystem
:class:`SoulStore`. The memory realisation over this kernel
(:class:`bob.memory.adapters.SqliteMemoryRepo`) moved to ``bob.memory.adapters``
(BOB-062.7b); memory recall + local embeddings moved there earlier (BOB-062.2);
the proactivity/goal/self-improvement stores moved to ``bob.proactivity.adapters``
(BOB-062.3). The schema is bundled here as ``schema.sql``.
"""

from __future__ import annotations

from bob.conversation.adapters.closer_log_store import SqliteCloserLog
from bob.conversation.adapters.conversation_floor_store import (
    SqliteConversationFloorStore,
)
from bob.infrastructure.persistence.connection import SqliteConnection
from bob.personality.adapters.fascination_store import SqliteFascinationStore
from bob.personality.adapters.notable_reaction_store import KvNotableReactionStore

# Social identity stores (first-impression / relationship / sulk / allowlist / soul)
# moved to ``bob.social.adapters`` (BOB-062.5); re-exported here so the persistence
# facade keeps resolving them unchanged.
from bob.social.adapters.allowlist_store import KvAllowlistStore
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.adapters.relationship_store import SqliteRelationshipStore
from bob.social.adapters.soul_store import SoulStore
from bob.social.adapters.sulk_store import SqliteSulkStore

__all__ = [
    "KvAllowlistStore",
    "KvNotableReactionStore",
    "SoulStore",
    "SqliteCloserLog",
    "SqliteConnection",
    "SqliteConversationFloorStore",
    "SqliteFascinationStore",
    "SqliteFirstImpressionStore",
    "SqliteRelationshipStore",
    "SqliteSulkStore",
]
