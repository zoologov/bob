# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""LLM infrastructure: OpenAI-compatible provider + Tier 0/1 factory."""

from __future__ import annotations

from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

__all__ = ["OpenAICompatProvider", "build_tier_providers"]
