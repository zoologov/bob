# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Persistence adapters — the shared SQLite connection/schema kernel.

Home of :class:`~bob.infrastructure.persistence.connection.SqliteConnection` — the
pure-I/O connection/schema kernel (WAL, sqlite-vec load, ``schema.sql``, kv) that
every durable store reads through its ``connection`` seam. This facade exports
*only* the kernel it actually owns: the durable stores that once lived here have
moved to their owning bounded contexts — the memory realisation to
``bob.memory.adapters`` (:class:`~bob.memory.adapters.SqliteMemoryRepo`, BOB-062.7b;
recall + local embeddings BOB-062.2), the proactivity/goal/self-improvement stores
to ``bob.proactivity.adapters`` (BOB-062.3), and the personality / conversation /
social identity stores to their respective ``adapters`` packages (BOB-062.4-.6).
Import each from its owning module (the canon path); this kernel no longer
re-exports them, so persistence depends on no business context. The schema is
bundled here as ``schema.sql``.
"""

from __future__ import annotations

from bob.infrastructure.persistence.connection import SqliteConnection

__all__ = [
    "SqliteConnection",
]
