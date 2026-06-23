# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``search_memory`` capability — the first agentic GUPPI skill.

Where ``recall_memory`` is the thin auto-recall, ``search_memory`` is the skill
Bob *chooses* to call: he decides to search his own long-term memory with a real
query over the full archive (the hybrid semantic+keyword recall) and uses the
result. The contract tests pin name/schema/permission and that ``execute``
delegates to the :class:`~bob.domain.ports.MemoryRecall` port with the right
query and ``k``; the e2e test drives the whole tool-loop on fakes: a reasoning
provider emits a ``search_memory`` tool_call, the registry dispatches it against
a fake recall, and the model finalises an answer that uses the recalled memory.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import pytest

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.capabilities.search_memory import make_search_memory_capability
from bob.application.capabilities.tool_loop import ToolLoop
from bob.domain.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.domain.ports import LLMMessage, Recalled, ToolDefinition


class FakeRecall:
    """A scripted :class:`MemoryRecall`: records calls, returns canned hits."""

    def __init__(self, hits: Sequence[Recalled]) -> None:
        self._hits = list(hits)
        self.calls: list[tuple[str, int]] = []

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        del surface_old  # this capability never asks for the BOB-021 old blend
        self.calls.append((query, k))
        return self._hits


class ScriptedToolProvider:
    """Returns a scripted sequence of ToolCallResults, one per model turn."""

    def __init__(self, results: Sequence[ToolCallResult]) -> None:
        self._results = list(results)
        self.turns: list[list[dict[str, str]]] = []
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        index = min(self._call, len(self._results) - 1)
        self._call += 1
        return self._results[index]

    @property
    def all_text(self) -> str:
        return "\n".join(m["content"] for turn in self.turns for m in turn)


def test_capability_advertises_the_search_memory_contract() -> None:
    # Arrange / Act
    cap = make_search_memory_capability(FakeRecall([]))

    # Assert: the stable seam fields the model reads to pick this agentic tool.
    assert cap.name == "search_memory"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert isinstance(properties["query"], Mapping)
    assert properties["query"]["type"] == "string"
    # ``k`` is an optional integer the model may tune; only ``query`` is required.
    assert isinstance(properties["k"], Mapping)
    assert properties["k"]["type"] == "integer"
    assert schema["required"] == ["query"]


async def test_execute_delegates_query_to_recall_and_returns_hits() -> None:
    # Arrange
    recall = FakeRecall(
        [
            {"content": "your name is Ada", "source": "semantic", "score": -1.2},
            {"content": "you like jazz", "source": "episodic", "score": -0.7},
        ]
    )
    cap = make_search_memory_capability(recall)

    # Act
    result = await cap.execute({"query": "what does Bob know about me"})

    # Assert: the hybrid recall was asked, hits are surfaced compactly.
    assert recall.calls == [("what does Bob know about me", 8)]
    assert isinstance(result, Mapping)
    items = result["results"]
    assert isinstance(items, list)
    assert items == ["your name is Ada", "you like jazz"]


async def test_execute_honours_a_model_supplied_k() -> None:
    # Arrange: the model is allowed to tune how many memories to pull back.
    recall = FakeRecall([{"content": "fact", "source": "semantic"}])
    cap = make_search_memory_capability(recall)

    # Act
    await cap.execute({"query": "history", "k": 3})

    # Assert: the override reaches the recall port verbatim.
    assert recall.calls == [("history", 3)]


async def test_execute_clamps_a_non_positive_k_to_the_default() -> None:
    # Arrange
    recall = FakeRecall([])
    cap = make_search_memory_capability(recall)

    # Act: a model may emit junk; a non-positive k is meaningless, not a request.
    await cap.execute({"query": "a", "k": 0})
    await cap.execute({"query": "b", "k": -4})

    # Assert: each clamps back to the safe default window.
    assert recall.calls == [("a", 8), ("b", 8)]


async def test_execute_caps_a_huge_k_at_the_ceiling() -> None:
    # Arrange
    recall = FakeRecall([])
    cap = make_search_memory_capability(recall)

    # Act: an over-eager request must not flood context with marginal hits.
    await cap.execute({"query": "c", "k": 9999})

    # Assert: capped at the ceiling, not passed through verbatim.
    assert recall.calls == [("c", 50)]


async def test_execute_ignores_a_non_integer_k() -> None:
    # Arrange
    recall = FakeRecall([])
    cap = make_search_memory_capability(recall)

    # Act: a stringy ``k`` from a sloppy model falls back to the default.
    await cap.execute({"query": "q", "k": "lots"})

    # Assert
    assert recall.calls == [("q", 8)]


async def test_execute_with_no_hits_returns_empty_results() -> None:
    # Arrange
    cap = make_search_memory_capability(FakeRecall([]))

    # Act
    result = await cap.execute({"query": "anything"})

    # Assert
    assert isinstance(result, Mapping)
    assert result["results"] == []


async def test_execute_requires_a_string_query() -> None:
    # Arrange
    cap = make_search_memory_capability(FakeRecall([]))

    # Act / Assert: a missing/typed-wrong query is a contract error, not a search.
    with pytest.raises(ValueError, match="query"):
        await cap.execute({})


async def test_tool_loop_e2e_search_memory_on_fakes() -> None:
    # Arrange: a fake hybrid recall holding the memory, registered as search_memory;
    # the reasoning provider decides to search (empty text + tool_call), then uses
    # the recalled memory to finalise — the realistic agentic round-trip.
    recall = FakeRecall(
        [{"content": "Ada loves the cello", "source": "semantic", "score": -0.9}]
    )
    registry = CapabilityRegistry()
    registry.register(make_search_memory_capability(recall))
    call = ToolCall(
        id="call_0",
        name="search_memory",
        arguments={"query": "what instrument does Ada love"},
    )
    provider = ScriptedToolProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Ada loves the cello.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=registry)

    # Act
    answer = await loop.run(
        [{"role": "user", "content": "remind me what instrument I love"}]
    )

    # Assert: GUPPI ran the agentic search, the hit reached the next turn, final text.
    assert recall.calls == [("what instrument does Ada love", 8)]
    assert "Ada loves the cello" in provider.all_text
    assert answer == "Ada loves the cello."
