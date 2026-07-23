# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=infrastructure

"""Proactivity infrastructure adapters — the durable stores + live read-seams.

Realise the proactivity module's outward ports over the shared SQLite kernel
(``SqliteMemoryRepo.connection()`` seam, BOB-062.3 variant C — the kernel stays
in ``bob.infrastructure.persistence``):

* :class:`SqliteProactivityStore` (:class:`~bob.proactivity.ports.ProactivityStore`)
  — per-persona drive/reservoir state over ``proactivity_state``.
* :class:`SqliteGoalStore` (:class:`~bob.proactivity.ports.GoalStore`) — the goal
  graph over the ``goal`` / ``task`` tables (Goal Engine, BOB-015).
* :class:`SqliteSelfImprovementStore`
  (:class:`~bob.proactivity.ports.SelfImprovementStore`) — curated rules over
  ``improvement_rule`` (BOB-028).
* :class:`RepoProactivitySources` — the cheap no-LLM read-seams the engine reads
  straight off the live ``episodic_log`` on every heartbeat tick.
"""

from bob.proactivity.adapters.goal_store import SqliteGoalStore
from bob.proactivity.adapters.proactivity_sources import RepoProactivitySources
from bob.proactivity.adapters.proactivity_store import SqliteProactivityStore
from bob.proactivity.adapters.self_improvement_store import SqliteSelfImprovementStore

__all__ = [
    "RepoProactivitySources",
    "SqliteGoalStore",
    "SqliteProactivityStore",
    "SqliteSelfImprovementStore",
]
