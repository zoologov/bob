# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Port protocols — the contracts the domain depends on (hexagonal boundary).

These are *interfaces only*: structural :class:`typing.Protocol` definitions with
no implementations. Adapters in ``bob.infrastructure`` realise them; ``bob.app``
wires concrete adapters to these ports. The domain never imports outward, so it
talks to transport / LLM / storage / time exclusively through these protocols.

This package was split from a single ``ports.py`` (BOB-065): the definitions now
live in cohesive submodules (``kernel`` / ``capabilities`` / ``memory`` /
``personality`` / ``conversation`` / ``social`` / ``proactivity`` / ``coding``).
This module is a **re-export shim** — ``from bob.domain.ports import X`` resolves
every one of the 51 public symbols unchanged, so importers never had to move.
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
from bob.coding.ports import (
    ClaudeCodeRunner,
    CodingSessionStore,
    PullRequestOpener,
    Worktree,
)
from bob.domain.ports.conversation import CloserLog, ConversationFloorStore
from bob.domain.ports.kernel import (
    Clock,
    DomainEvent,
    EventBus,
    EventHandler,
    JsonValue,
    LLMMessage,
    LLMProvider,
)
from bob.domain.ports.personality import (
    FascinationStore,
    FirstImpressionStore,
    MessageReactor,
    NotableReactionStore,
    ReflectionReader,
    RelationshipStore,
    SulkStore,
    ZoneClassifier,
)
from bob.domain.ports.social import AllowlistStore, SoulStore
from bob.memory.ports import (
    Embedder,
    MemoryRecall,
    MemoryRepo,
    Recalled,
    Reranker,
)
from bob.proactivity.ports import (
    GoalStore,
    PatternDetector,
    Planner,
    ProactivityStore,
    SelfImprovementStore,
)

__all__ = [
    "AllowlistStore",
    "Capability",
    "ClaudeCodeRunner",
    "Clock",
    "CloserLog",
    "CodingSessionStore",
    "ConversationFloorStore",
    "DiagramRenderError",
    "DiagramRenderer",
    "DiagramResult",
    "DiagramSink",
    "DomainEvent",
    "Embedder",
    "EventBus",
    "EventHandler",
    "FascinationStore",
    "FirstImpressionStore",
    "GoalStore",
    "JsonValue",
    "LLMMessage",
    "LLMProvider",
    "MemoryRecall",
    "MemoryRepo",
    "MessageReactor",
    "NotableReactionStore",
    "PatternDetector",
    "Permission",
    "Planner",
    "ProactivityStore",
    "PullRequestOpener",
    "Recalled",
    "ReflectionReader",
    "RelationshipStore",
    "RepoIntrospector",
    "Reranker",
    "SelfImprovementStore",
    "SoulStore",
    "SsrfBlockedError",
    "SulkStore",
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
    "Worktree",
    "ZoneClassifier",
]
