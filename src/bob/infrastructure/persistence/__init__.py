# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Persistence adapters — the shared SQLite store kernel and SoulStore.

Realises the domain's storage port (:class:`bob.domain.ports.MemoryRepo` via
``SqliteMemoryRepo``) plus every module's durable store over one connection
seam. All SQL and filesystem I/O for Bob's durable state live here; the schema
is bundled as ``schema.sql``. Memory recall + local embeddings moved to
``bob.memory.adapters`` (BOB-062.2); the proactivity/goal/self-improvement stores
moved to ``bob.proactivity.adapters`` (BOB-062.3); the store kernel splits out in
a later slice.
"""

from __future__ import annotations

from bob.conversation.adapters.closer_log_store import SqliteCloserLog
from bob.conversation.adapters.conversation_floor_store import (
    SqliteConversationFloorStore,
)
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
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
    "SqliteConversationFloorStore",
    "SqliteFascinationStore",
    "SqliteFirstImpressionStore",
    "SqliteMemoryRepo",
    "SqliteRelationshipStore",
    "SqliteSulkStore",
]
