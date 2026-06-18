# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Memory domain — pure entities for episodic and semantic memory.

No I/O lives here: these are immutable value objects that the persistence
adapter (``bob.infrastructure.persistence``) maps to and from SQLite rows.
"""

from __future__ import annotations

from bob.domain.memory.entities import EpisodicEvent, SemanticFact

__all__ = ["EpisodicEvent", "SemanticFact"]
