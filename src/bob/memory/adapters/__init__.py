# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""Memory infrastructure adapters — recall and local embeddings.

Realise the memory module's outward ports (:mod:`bob.memory.ports`): relevance
recall (:class:`Fts5MemoryRecall` P0 keyword; :class:`HybridMemoryRecall` FTS5 +
sqlite-vec with an optional reranker) and the local, provider-agnostic semantic
seams (:class:`OllamaEmbedder` + :func:`build_embedder`; :class:`OllamaReranker`
+ :func:`build_reranker`). All memory content stays on the machine.

The durable episode/fact store (``SqliteMemoryRepo``) is a shared persistence
kernel and stays in ``bob.infrastructure.persistence`` until the runtime slice.
"""

from __future__ import annotations

from bob.memory.adapters.embedder_factory import build_embedder
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.hybrid_recall import HybridMemoryRecall
from bob.memory.adapters.ollama_embedder import OllamaEmbedder
from bob.memory.adapters.ollama_reranker import OllamaReranker
from bob.memory.adapters.reranker_factory import build_reranker

__all__ = [
    "Fts5MemoryRecall",
    "HybridMemoryRecall",
    "OllamaEmbedder",
    "OllamaReranker",
    "build_embedder",
    "build_reranker",
]
