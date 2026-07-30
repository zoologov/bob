# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening for ToolLoop (US-4) — capability-failure and result-rendering edges.

These pin the seam's *robustness* contract: a capability raising a non-protocol
error must surface as a fed-back ``tool`` error message (GUPPI's job failing, not
the turn crashing), and a non-JSON-serialisable result must still render into the
``tool`` message without exploding. They complement ``test_tool_loop.py`` (happy
path + unknown tool + turn cap) by covering the two remaining failure branches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.ports import ToolCall, ToolCallResult
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import Permission, ToolDefinition
    from bob.kernel.ports import ToolLoopMessage


class _Capability:
    """A capability whose execute result/behaviour the test controls."""

    name = "recall_memory"
    description = "Search memory."
    input_schema: Mapping[str, object] = {"type": "object", "properties": {}}
    permission: Permission = "safe"

    def __init__(self, *, result: object = "RECALLED", boom: bool = False) -> None:
        self._result = result
        self._boom = boom
        self.calls = 0

    async def execute(self, args: Mapping[str, object]) -> object:  # noqa: ARG002
        self.calls += 1
        if self._boom:
            raise RuntimeError("capability blew up")
        return self._result


class _ScriptedProvider:
    """Returns a scripted ToolCallResult per turn (mirrors test_tool_loop)."""

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


def _registry(cap: _Capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(cap)
    return registry


def _seed() -> list[ToolLoopMessage]:
    return [{"role": "user", "content": "recall something"}]


async def test_capability_exception_is_fed_back_as_tool_error_not_raised() -> None:
    # Arrange: the capability raises a real (non-protocol) error mid-dispatch; the
    # model recovers on the next turn. GUPPI's executor failing must not crash the
    # loop — the failure is reported back as the tool result.
    cap = _Capability(boom=True)
    call = ToolCall(id="c1", name="recall_memory", arguments={"query": "x"})
    provider = _ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="No worries, moving on.", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap))

    # Act
    answer = await loop.run(_seed())

    # Assert: the dispatch was attempted, the error was fed back, the loop finished.
    assert cap.calls == 1
    assert "error: capability 'recall_memory' failed" in provider.all_text
    assert answer == "No worries, moving on."


async def test_non_serialisable_capability_result_renders_via_str() -> None:
    # Arrange: a capability whose result is a structure json.dumps cannot encode
    # (a set). The renderer must fall back to str() rather than raise, so the
    # result still reaches the model as a tool message.
    cap = _Capability(result={"unjsonable", "set"})
    call = ToolCall(id="c1", name="recall_memory", arguments={})
    provider = _ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="done", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap))

    # Act
    answer = await loop.run(_seed())

    # Assert: a tool message carrying the stringified set was fed back; no crash.
    tool_turn = provider.turns[-1]
    tool_messages = [m for m in tool_turn if m.get("role") == "tool"]
    assert tool_messages
    assert "unjsonable" in str(tool_messages[-1]["content"])
    assert answer == "done"


async def test_mapping_result_is_rendered_as_json() -> None:
    # Arrange: a JSON-serialisable mapping result must be rendered as JSON (the
    # normal _render_result path), preserving structure for the model.
    cap = _Capability(result={"hits": ["a", "b"]})
    call = ToolCall(id="c1", name="recall_memory", arguments={})
    provider = _ScriptedProvider(
        [
            ToolCallResult(text="", tool_calls=(call,)),
            ToolCallResult(text="ok", tool_calls=()),
        ]
    )
    loop = ToolLoop(provider=provider, registry=_registry(cap))

    # Act
    await loop.run(_seed())

    # Assert: the tool message carries JSON (keys quoted), proving json.dumps ran.
    tool_messages = [m for m in provider.turns[-1] if m.get("role") == "tool"]
    assert '"hits"' in str(tool_messages[-1]["content"])
