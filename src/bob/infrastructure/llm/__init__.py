# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LLM infrastructure: OpenAI-compatible provider + Tier 0/1 + local embedder."""

from __future__ import annotations

from bob.infrastructure.llm.embedder_factory import build_embedder
from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.llm.ollama_embedder import OllamaEmbedder
from bob.infrastructure.llm.ollama_reranker import OllamaReranker
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider
from bob.infrastructure.llm.reranker_factory import build_reranker

__all__ = [
    "OllamaEmbedder",
    "OllamaReranker",
    "OpenAICompatProvider",
    "build_embedder",
    "build_reranker",
    "build_tier_providers",
]
