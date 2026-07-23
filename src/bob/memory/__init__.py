# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Memory module — the «Bob remembers» capability (BOB-062.2).

Screaming-architecture home for episodic/semantic memory: the pure entities
and contracts live here (``entities`` / ``ports``), the digest/extract/dedup
orchestration in ``usecases``, and the recall + local-embedding realisations in
``adapters``. No I/O lives at this facade — the entities are immutable value
objects that the persistence adapter maps to and from SQLite rows.
"""

from __future__ import annotations

from bob.memory.entities import EpisodicEvent, SemanticFact

__all__ = ["EpisodicEvent", "SemanticFact"]
