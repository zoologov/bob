# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Capabilities module («Bob's tools») — the GUPPI tool seam as one vertical.

The full capability slice in one bounded context (domain-first slice BOB-062.4):
the stable :class:`Capability` contract and its sibling ports (``ports.py``), the
pure ``diagrams`` / ``introspection`` value objects, the ``usecases`` half
(``CapabilityRegistry`` + ``ToolLoop`` and the individual skills — recall/search
memory, read code/url, web search, render diagram, inspect architecture, progress
announcer), and the ``adapters`` half (HTTP url-reader + SSRF guard, mermaid
renderer, beadloom/git introspector, Qwen web-search transport).

The package facade re-exports only the stable *ports* — the tool-seam contract the
outer layers depend on.
"""

from __future__ import annotations

from bob.capabilities.ports import (
    Capability,
    DiagramRenderer,
    DiagramRenderError,
    DiagramResult,
    DiagramSink,
    Permission,
    RepoIntrospector,
    SsrfBlockedError,
    ToolCall,
    ToolCallingProvider,
    ToolCallResult,
    ToolDefinition,
    UrlReader,
    UrlReadError,
    WebPage,
    WebSearchProvider,
    WebSearchResult,
    WebSource,
)

__all__ = [
    "Capability",
    "DiagramRenderError",
    "DiagramRenderer",
    "DiagramResult",
    "DiagramSink",
    "Permission",
    "RepoIntrospector",
    "SsrfBlockedError",
    "ToolCall",
    "ToolCallResult",
    "ToolCallingProvider",
    "ToolDefinition",
    "UrlReadError",
    "UrlReader",
    "WebPage",
    "WebSearchProvider",
    "WebSearchResult",
    "WebSource",
]
