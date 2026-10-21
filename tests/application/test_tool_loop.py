# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ToolLoop — drive the model<->tools round-trip until a final answer.

The loop sends the manifest as tools; while the model requests tool calls it
dispatches them through the registry (GUPPI executes), feeds each result back as
a ``tool`` message, and re-asks — stopping on a final text answer or a turn cap.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop, _assistant_turn
from bob.kernel.ports import ToolCall, ToolCallResult
from bob.memory.self_action import SelfActionKind

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import Permission
    from bob.kernel.ports import ToolDefinition, ToolLoopMessage
    from bob.memory.self_action import SelfAction


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
        self.turns: list[list[dict[str, object]]] = []
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        index = min(self._call, len(self._results) - 1)
        self._call += 1
        return self._results[index]

    @property
    def all_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for turn in self.turns for m in turn)


def _registry(cap: FakeCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(cap)
    return registry


def _seed() -> list[ToolLoopMessage]:
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


# --- _assistant_turn — structural OpenAI tool_calls shape (BOB-069 B) ---------
# 🔴 Регресс живого бага: раньше _assistant_turn зашивал tool-интент СТРОКОЙ в
# content (f"[tool_calls] {rendered}"), из-за чего re-ask был малформ по OpenAI,
# Qwen эхом повторял строку и она утекала в чат. Теперь ход СТРУКТУРНЫЙ.


def _tool_calls_of(turn: ToolLoopMessage) -> list[Any]:
    """Narrow the ``tool_calls`` value (typed ``object`` on ToolLoopMessage) to a list."""
    calls = turn["tool_calls"]
    assert isinstance(calls, list)
    return calls


def test_assistant_turn_is_structural_openai_tool_calls() -> None:
    # Arrange: один запрошенный tool-call.
    call = ToolCall(id="call_7", name="read_code", arguments={"query": "x.feature"})

    # Act
    turn = _assistant_turn((call,))

    # Assert: OpenAI-структурный ход — tool_calls-массив, а НЕ content-строка.
    assert turn["role"] == "assistant"
    assert not str(turn.get("content", "")).startswith("[tool_calls]")
    tool_calls = _tool_calls_of(turn)
    assert len(tool_calls) == 1
    entry = tool_calls[0]
    assert entry["type"] == "function"
    assert entry["function"]["name"] == "read_code"


def test_assistant_turn_arguments_is_json_string_not_dict() -> None:
    # 🔴 OpenAI ждёт arguments как JSON-СТРОКУ, не dict.
    call = ToolCall(id="c1", name="read_code", arguments={"query": "a/b.feature"})

    entry = _tool_calls_of(_assistant_turn((call,)))[0]

    arguments = entry["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"query": "a/b.feature"}


def test_assistant_turn_id_matches_the_tool_result_id() -> None:
    # 🔴 id ассистент-хода обязан совпасть с tool_call_id результата (_run_tool
    # кладёт call.id) — иначе модель не свяжет tool-результат с вызовом.
    call = ToolCall(id="the-id", name="read_code", arguments={})

    entry = _tool_calls_of(_assistant_turn((call,)))[0]

    assert entry["id"] == call.id


def test_assistant_turn_renders_every_call_in_order() -> None:
    calls = (
        ToolCall(id="a", name="read_code", arguments={"q": "1"}),
        ToolCall(id="b", name="list_dir", arguments={"path": "."}),
    )

    tool_calls = _tool_calls_of(_assistant_turn(calls))

    assert [c["id"] for c in tool_calls] == ["a", "b"]
    assert [c["function"]["name"] for c in tool_calls] == ["read_code", "list_dir"]


async def test_assistant_turn_never_leaks_tool_calls_string_into_conversation() -> None:
    # Инвариант через петлю: после дубль-хода ни одно сообщение в истории,
    # переданной модели, не начинается с сырого «[tool_calls] ».
    cap = FakeCapability(result="ok")
    call = ToolCall(id="c1", name="recall_memory", arguments={"q": "x"})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap))

    await loop.run(_seed())

    for turn in provider.turns:
        for message in turn:
            assert not str(message.get("content", "")).startswith("[tool_calls]")


# --- Self-action recording (BOB-079.3) — coalesced TOOL_USE + per-tool TOOL_FAILURE -----
# 🔴 One episode per turn max (avoid the BOB-076 flood): successful tool names are
# COALESCED into a single TOOL_USE at the end of the run; a failing tool records its own
# TOOL_FAILURE and is excluded from the coalesced names; a no-tool run writes NOTHING; and
# a recorder that raises never breaks the loop or the reply (best-effort, lesson BOB-078 D).


class NamedCapability(FakeCapability):
    """A FakeCapability with a caller-chosen name (default FakeCapability is fixed-name)."""

    def __init__(self, name: str, *, result: object = "ok") -> None:
        super().__init__(result=result)
        self.name = name


class FailingCapability(FakeCapability):
    """A capability whose dispatch raises — drives the TOOL_FAILURE branch of the loop."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    async def execute(self, args: Mapping[str, object]) -> object:  # noqa: ARG002
        raise RuntimeError("boom: tool exploded")


class SpyRecorder:
    """A fake SelfActionRecorder that captures every recorded action + its sender/visibility."""

    def __init__(self) -> None:
        self.actions: list[SelfAction] = []
        self.senders: list[int | None] = []
        self.visibilities: list[str | None] = []

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        self.actions.append(action)
        self.senders.append(sender_id)
        self.visibilities.append(visibility)


class RaisingRecorder:
    """A recorder that always raises — proves recording faults are swallowed best-effort."""

    async def record(
        self,
        action: SelfAction,  # noqa: ARG002
        *,
        sender_id: int | None = None,  # noqa: ARG002
        visibility: str | None = None,  # noqa: ARG002
    ) -> None:
        raise RuntimeError("db down")


def _two_cap_registry(*caps: FakeCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for cap in caps:
        registry.register(cap)
    return registry


async def test_two_successful_calls_coalesce_into_one_tool_use_with_both_names() -> None:
    # Arrange: one turn requests two DIFFERENT tools, both succeed; the loop then finalises.
    calls = (
        ToolCall(id="c1", name="read_code", arguments={}),
        ToolCall(id="c2", name="list_dir", arguments={}),
    )
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=calls),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    recorder = SpyRecorder()
    loop = ToolLoop(
        provider=provider,
        registry=_two_cap_registry(
            NamedCapability("read_code"), NamedCapability("list_dir")
        ),
        recorder=recorder,
    )

    # Act
    answer = await loop.run(_seed())

    # Assert: exactly ONE TOOL_USE episode carrying both names (first-seen order), no floods.
    assert answer == "done"
    assert len(recorder.actions) == 1
    action = recorder.actions[0]
    assert action.kind is SelfActionKind.TOOL_USE
    assert action.target == "read_code, list_dir"


async def test_repeated_tool_name_is_recorded_once_in_tool_use() -> None:
    # Arrange: the SAME tool is called twice in one turn — the coalesced names dedup.
    calls = (
        ToolCall(id="c1", name="read_code", arguments={"q": "1"}),
        ToolCall(id="c2", name="read_code", arguments={"q": "2"}),
    )
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=calls),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    recorder = SpyRecorder()
    loop = ToolLoop(
        provider=provider,
        registry=_two_cap_registry(NamedCapability("read_code")),
        recorder=recorder,
    )

    await loop.run(_seed())

    assert len(recorder.actions) == 1
    assert recorder.actions[0].target == "read_code"


async def test_failing_tool_records_failure_and_is_excluded_from_tool_use() -> None:
    # Arrange: one good tool + one that raises, both in the same turn.
    calls = (
        ToolCall(id="c1", name="read_code", arguments={}),
        ToolCall(id="c2", name="web_search", arguments={}),
    )
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=calls),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    recorder = SpyRecorder()
    loop = ToolLoop(
        provider=provider,
        registry=_two_cap_registry(
            NamedCapability("read_code"), FailingCapability("web_search")
        ),
        recorder=recorder,
    )

    # Act
    answer = await loop.run(_seed())

    # Assert: the loop recovers; a TOOL_FAILURE names the failed tool with a short detail,
    # and the coalesced TOOL_USE lists only the SUCCESSFUL tool.
    assert answer == "done"
    kinds = [a.kind for a in recorder.actions]
    assert SelfActionKind.TOOL_FAILURE in kinds
    failure = next(a for a in recorder.actions if a.kind is SelfActionKind.TOOL_FAILURE)
    assert failure.target == "web_search"
    assert failure.detail  # a short reason is attached
    tool_use = next(a for a in recorder.actions if a.kind is SelfActionKind.TOOL_USE)
    assert tool_use.target == "read_code"


async def test_run_with_no_tool_calls_records_nothing() -> None:
    # Arrange: the model answers straight away, no tools — the common case, zero-write.
    provider = ScriptedProvider([ToolCallResult(text="Hello!", tool_calls=())])
    recorder = SpyRecorder()
    loop = ToolLoop(
        provider=provider,
        registry=_two_cap_registry(NamedCapability("read_code")),
        recorder=recorder,
    )

    # Act
    answer = await loop.run(_seed())

    # Assert: no episode at all.
    assert answer == "Hello!"
    assert recorder.actions == []


async def test_a_raising_recorder_never_breaks_the_run() -> None:
    # Arrange: a recorder that always raises + one successful tool call.
    call = ToolCall(id="c1", name="read_code", arguments={})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    loop = ToolLoop(
        provider=provider,
        registry=_two_cap_registry(NamedCapability("read_code")),
        recorder=RaisingRecorder(),
    )

    # Act — must NOT raise; the reply is unaffected.
    answer = await loop.run(_seed())

    # Assert
    assert answer == "done"


async def test_no_recorder_wired_behaves_exactly_as_before() -> None:
    # Arrange: the default (no recorder) dispatches + answers unchanged.
    call = ToolCall(id="c1", name="read_code", arguments={})
    provider = ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    loop = ToolLoop(
        provider=provider, registry=_two_cap_registry(NamedCapability("read_code"))
    )

    answer = await loop.run(_seed())

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
