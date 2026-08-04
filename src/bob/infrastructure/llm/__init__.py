# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LLM infrastructure: OpenAI-compatible provider + Tier 0/1 providers.

The local embedder/reranker adapters moved to ``bob.memory.adapters`` (BOB-062.2),
where the «Bob remembers» capability owns its embedding seams.
"""

from __future__ import annotations

from bob.infrastructure.llm.factory import (
    build_tier_providers,
    build_web_search_provider,
)
from bob.infrastructure.llm.fallback_provider import (
    FallbackLLMProvider,
    ToolCallingFallbackLLMProvider,
    build_fallback_provider,
)
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

__all__ = [
    "FallbackLLMProvider",
    "OpenAICompatProvider",
    "ToolCallingFallbackLLMProvider",
    "build_fallback_provider",
    "build_tier_providers",
    "build_web_search_provider",
]
