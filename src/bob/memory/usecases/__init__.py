# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:feature=memory
# beadloom:layer=application

"""Memory use-cases — orchestration of the «Bob remembers» capability.

The application layer of the ``memory`` module: fact extraction after a turn,
and the rare, non-destructive maturation steps (consolidation of old episodes
into digests, conservative merge of near-duplicate facts). Each drives the pure
domain through :mod:`bob.memory.ports`, keeping I/O at the adapter edge.
"""

from __future__ import annotations

from bob.memory.usecases.classify_work_talk import ClassifyWorkTalk
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.dedup_facts import DedupFacts
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.memory.usecases.resolve_register import RegisterResolver

__all__ = [
    "ClassifyWorkTalk",
    "ConsolidateMemory",
    "DedupFacts",
    "ExtractFacts",
    "RegisterResolver",
]
