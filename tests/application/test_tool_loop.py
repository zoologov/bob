# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ToolLoop — drive the model<->tools round-trip until a final answer.

The loop sends the manifest as tools; while the model requests tool calls it
dispatches them through the registry (GUPPI executes), feeds each result back as
a ``tool`` message, and re-asks — stopping on a final text answer or a turn cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.domain.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.domain.ports import LLMMessage, Permission, ToolDefinition


class FakeCapability:
    name = "recall_memory"
    description = "Search memory."
    input_schema: Mapping[str, object] = {"type": "object", "properties": {}}
    permission: Permission = "safe"

    def __init__(self, *, result: object = "RECALLED") -> None:
        self._result = result
        self.calls: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        return self._result


class ScriptedProvider:
    """Returns a scripted sequence of ToolCallResults, one per turn."""

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


def _registry(cap: FakeCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(cap)
    return registry


def _seed() -> list[LLMMessage]:
    return [{"role": "user", "content": "what's my name?"}]


async def test_returns_final_answer_immediately_when_no_tool_calls() -> None:
    # Arrange
    provider = ScriptedProvider([ToolCallResult(text="Hello!", tool_calls=())])
    loop = ToolLoop(provider=provider, registry=_registry(FakeCapability()))

    # Act
    answer = await loop.run(_seed())

    # Assert
    assert answer == "Hello!"
    assert len(provider.turns) == 1


async def test_dispatches_tool_then_feeds_result_back_to_final_answer() -> None:
    # Arrange: turn 1 requests recall_memory; turn 2 answers with the result fed in.
    cap = FakeCapability(result="your name is Ada")
    call = ToolCall(id="c1", name="recall_memory", arguments={"query": "name"})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Your name is Ada.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap))

    # Act
    answer = await loop.run(_seed())

    # Assert: GUPPI executed the tool, its result reached the next turn, final answer.
    assert cap.calls == [{"query": "name"}]
    assert "your name is Ada" in provider.all_text
    assert answer == "Your name is Ada."


async def test_unknown_tool_call_is_reported_back_not_raised() -> None:
    # Arrange: the model asks for a tool that is not registered.
    call = ToolCall(id="c1", name="does_not_exist", arguments={})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="Sorry, I cannot do that.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(FakeCapability()))

    # Act
    answer = await loop.run(_seed())

    # Assert: the error is fed back as a tool message; the loop recovers.
    assert "error" in provider.all_text.lower()
    assert answer == "Sorry, I cannot do that."


async def test_loop_stops_at_the_turn_cap_to_avoid_runaway() -> None:
    # Arrange: a provider that asks for a tool on every turn (never finalises).
    call = ToolCall(id="c", name="recall_memory", arguments={})
    provider = ScriptedProvider([ToolCallResult(text="", tool_calls=(call,))])
    loop = ToolLoop(provider=provider, registry=_registry(FakeCapability()), max_turns=3)

    # Act
    answer = await loop.run(_seed())

    # Assert: it bailed out at the cap (3 model turns) with a safe empty answer.
    assert len(provider.turns) == 3
    assert isinstance(answer, str)


def test_max_turns_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        ToolLoop(
            provider=ScriptedProvider([ToolCallResult(text="x")]),
            registry=CapabilityRegistry(),
            max_turns=0,
        )


class RecordingAnnouncer:
    """A fake ProgressAnnouncer that records the names + args it was asked to announce."""

    def __init__(self) -> None:
        self.announced: list[str] = []
        self.arguments: list[Mapping[str, object]] = []

    async def announce(
        self, capability_name: str, arguments: Mapping[str, object]
    ) -> None:
        self.announced.append(capability_name)
        self.arguments.append(arguments)


async def test_announcer_is_called_before_dispatch() -> None:
    # Arrange: turn 1 requests the tool; a recording announcer + a capability that
    # records the interleaving via a shared log proves announce fires BEFORE dispatch.
    order: list[str] = []

    class LoggingCapability(FakeCapability):
        async def execute(self, args: Mapping[str, object]) -> object:
            order.append("dispatch")
            return await super().execute(args)

    class LoggingAnnouncer(RecordingAnnouncer):
        async def announce(
            self, capability_name: str, arguments: Mapping[str, object]
        ) -> None:
            order.append("announce")
            await super().announce(capability_name, arguments)

    cap = LoggingCapability(result="ok")
    call = ToolCall(id="c1", name="recall_memory", arguments={})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    announcer = LoggingAnnouncer()
    loop = ToolLoop(provider=provider, registry=_registry(cap), announcer=announcer)

    # Act
    answer = await loop.run(_seed())

    # Assert: announce ran, with the tool name, strictly before the dispatch.
    assert announcer.announced == ["recall_memory"]
    assert order == ["announce", "dispatch"]
    assert answer == "done"


async def test_announcer_receives_the_call_arguments_so_the_query_flows_as_topic() -> None:
    # 🔴 BOB-060 US-2 wiring: the loop forwards the call's ARGUMENTS (not just its name)
    # to announce — so a web_search's ``query`` reaches the announcer and becomes the
    # topic of Bob's LIVE interim line (a scripted abstract «ищу…» is impossible).
    cap = FakeCapability(result="ok")
    call = ToolCall(
        id="c1", name="recall_memory", arguments={"query": "свежая ставка ЦБ"}
    )
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    announcer = RecordingAnnouncer()
    loop = ToolLoop(provider=provider, registry=_registry(cap), announcer=announcer)

    answer = await loop.run(_seed())

    assert announcer.announced == ["recall_memory"]
    assert announcer.arguments == [{"query": "свежая ставка ЦБ"}]  # query forwarded whole
    assert answer == "done"


async def test_announcer_fires_once_per_call_in_order_for_multiple_tool_calls() -> None:
    # Arrange: a single turn requests the SAME tool twice — the announcer must fire
    # exactly once per call and strictly before each dispatch (no batching, no double
    # announce), so every slow hop gets its own interim line in order.
    order: list[str] = []

    class LoggingCapability(FakeCapability):
        async def execute(self, args: Mapping[str, object]) -> object:
            order.append("dispatch")
            return await super().execute(args)

    class LoggingAnnouncer(RecordingAnnouncer):
        async def announce(
            self, capability_name: str, arguments: Mapping[str, object]
        ) -> None:
            order.append("announce")
            await super().announce(capability_name, arguments)

    cap = LoggingCapability(result="ok")
    calls = (
        ToolCall(id="c1", name="recall_memory", arguments={"q": "1"}),
        ToolCall(id="c2", name="recall_memory", arguments={"q": "2"}),
    )
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=calls),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    announcer = LoggingAnnouncer()
    loop = ToolLoop(provider=provider, registry=_registry(cap), announcer=announcer)

    # Act
    answer = await loop.run(_seed())

    # Assert: one announce per call, each paired before its dispatch, order preserved.
    assert announcer.announced == ["recall_memory", "recall_memory"]
    assert order == ["announce", "dispatch", "announce", "dispatch"]
    assert answer == "done"


async def test_announcer_none_behaves_as_before() -> None:
    # Arrange: no announcer wired (the default) → the loop dispatches unchanged.
    cap = FakeCapability(result="ok")
    call = ToolCall(id="c1", name="recall_memory", arguments={})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap), announcer=None)

    # Act
    answer = await loop.run(_seed())

    # Assert
    assert cap.calls == [{}]
    assert answer == "done"
