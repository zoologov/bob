# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Re-export shim contract for the ``bob.domain.ports`` package (BOB-065 .1).

``ports.py`` was split into a package (``kernel``/``capabilities``/``memory``/
``personality``/``conversation``/``social``/``proactivity``/``coding``). This test
locks the behaviour-preserving invariant: every one of the 51 public symbols still
imports from ``bob.domain.ports`` unchanged, and ``__all__`` is the exact union of
the prior 51 names — so the ~105 importers never touched need no change.
"""

from __future__ import annotations

from bob.domain import ports

EXPECTED_ALL: frozenset[str] = frozenset(
    {
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
    }
)


def test_all_lists_exactly_the_51_public_symbols() -> None:
    """``__all__`` is the exact union of the prior 51 names (no drift, no dupes)."""
    assert len(EXPECTED_ALL) == 51
    assert set(ports.__all__) == EXPECTED_ALL
    assert len(ports.__all__) == len(EXPECTED_ALL)  # no duplicates in __all__


def test_every_public_symbol_is_importable_from_the_package() -> None:
    """Each of the 51 symbols resolves as an attribute of ``bob.domain.ports``."""
    missing = [name for name in EXPECTED_ALL if not hasattr(ports, name)]
    assert missing == []
