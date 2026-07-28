# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``recall_memory`` capability — the first real GUPPI skill.

A thin wrapper over the :class:`~bob.domain.ports.MemoryRecall` port: it exposes
the stable :class:`~bob.domain.ports.Capability` contract, delegates a query to
``recall`` and renders the recalled items as a compact result. The e2e test then
drives the whole tool-loop on fakes: a provider asks for ``recall_memory``, the
registry dispatches it against a fake recall, and the model finalises an answer
that uses the recalled fact.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import pytest

from bob.capabilities.usecases.recall_memory import make_recall_memory_capability
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
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


def test_capability_advertises_the_recall_memory_contract() -> None:
    # Arrange / Act
    cap = make_recall_memory_capability(FakeRecall([]))

    # Assert: the stable seam fields the model uses to pick the tool.
    assert cap.name == "recall_memory"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["query"] == {"type": "string"}
    assert schema["required"] == ["query"]


async def test_execute_delegates_query_to_recall_and_returns_hits() -> None:
    # Arrange
    recall = FakeRecall(
        [
            {"content": "your name is Ada", "source": "semantic", "score": -1.2},
            {"content": "you like jazz", "source": "episodic", "score": -0.7},
        ]
    )
    cap = make_recall_memory_capability(recall)

    # Act
    result = await cap.execute({"query": "what is my name"})

    # Assert: the port was asked, and the hits are surfaced compactly.
    assert recall.calls == [("what is my name", 5)]
    assert isinstance(result, Mapping)
    items = result["results"]
    assert isinstance(items, list)
    assert items == ["your name is Ada", "you like jazz"]


async def test_execute_with_no_hits_returns_empty_results() -> None:
    # Arrange
    cap = make_recall_memory_capability(FakeRecall([]))

    # Act
    result = await cap.execute({"query": "anything"})

    # Assert
    assert isinstance(result, Mapping)
    assert result["results"] == []


async def test_execute_requires_a_string_query() -> None:
    # Arrange
    cap = make_recall_memory_capability(FakeRecall([]))

    # Act / Assert: a missing/typed-wrong query is a contract error, not a recall.
    with pytest.raises(ValueError, match="query"):
        await cap.execute({})


async def test_tool_loop_e2e_recall_memory_on_fakes() -> None:
    # Arrange: a fake recall holding the fact, registered as recall_memory; the
    # provider asks for the tool (reasoning-model tool_call shape) then finalises.
    recall = FakeRecall([{"content": "your name is Ada", "source": "semantic"}])
    registry = CapabilityRegistry()
    registry.register(make_recall_memory_capability(recall))
    call = ToolCall(id="call_0", name="recall_memory", arguments={"query": "my name"})
    provider = ScriptedToolProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Your name is Ada.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=registry)

    # Act
    answer = await loop.run([{"role": "user", "content": "what's my name?"}])

    # Assert: GUPPI delegated to recall, the fact reached the next turn, final answer.
    assert recall.calls == [("my name", 5)]
    assert "your name is Ada" in provider.all_text
    assert answer == "Your name is Ada."
