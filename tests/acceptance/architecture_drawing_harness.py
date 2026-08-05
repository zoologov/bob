# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture-drawing acceptance harness (BOB-091.1).

Drives Bob's read-only architecture tools THROUGH the boundary the BRIEF cares about —
the capability registry + the REAL
:class:`~bob.capabilities.usecases.tool_loop.ToolLoop` — over a scripted, disk-free
:class:`~tests.application.capabilities.fakes.FakeRepoIntrospector`. The scenarios
witness the OBSERVABLE outcome: the tool result that flows BACK to the model, never the
loop's internals or the port's private state — a grounded answer (and a rendered
picture) can only come from real tool output.

The flag scenarios use the REAL composition-root gate (``_build_registry``) over a
duck-typed recall fake, so "Bob never sees the tools when the flag is off" is asserted on
production wiring rather than on a comment.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bob.app import _build_registry
from bob.capabilities.ports import ToolCall, ToolCallResult
from bob.capabilities.usecases.architecture_impact import (
    make_architecture_impact_capability,
)
from bob.capabilities.usecases.draw_architecture import (
    make_draw_architecture_capability,
)
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import ToolDefinition
    from bob.kernel.ports import ToolLoopMessage
    from tests.application.capabilities.fakes import FakeRepoIntrospector


def _registry_over(introspector: FakeRepoIntrospector) -> CapabilityRegistry:
    """Register the two real architecture tools over the given scripted port."""
    registry = CapabilityRegistry()
    registry.register(make_draw_architecture_capability(introspector))
    registry.register(make_architecture_impact_capability(introspector))
    return registry


class _ToolProbeProvider:
    """A ``ToolCallingProvider`` that requests ONE tool, then finalises.

    Records the tool names it was OFFERED, their advertised descriptions, and the
    ``tool`` result content fed BACK to it — the observable boundary the scenarios
    assert on.
    """

    def __init__(self, tool_name: str, arguments: Mapping[str, object]) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._turn = 0
        self.offered_tools: list[str] = []
        self.offered_descriptions: dict[str, str] = {}
        self.fed_back_tool_results: list[str] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        self.offered_tools = [_tool_name(tool) for tool in tools]
        self.offered_descriptions = {
            _tool_name(tool): _tool_description(tool) for tool in tools
        }
        for message in messages:
            if message.get("role") == "tool":
                self.fed_back_tool_results.append(str(message.get("content", "")))
        self._turn += 1
        if self._turn == 1:
            return ToolCallResult(
                text="",
                tool_calls=(
                    ToolCall(id="c1", name=self._tool_name, arguments=self._arguments),
                ),
            )
        return ToolCallResult(text="Рассказываю своими словами.")


def _tool_field(tool: ToolDefinition, field: str) -> str:
    """Read one field of a tool definition's ``function`` object."""
    function = tool.get("function", {})
    value = function.get(field, "") if isinstance(function, dict) else ""
    return str(value)


def _tool_name(tool: ToolDefinition) -> str:
    return _tool_field(tool, "name")


def _tool_description(tool: ToolDefinition) -> str:
    return _tool_field(tool, "description")


async def run_architecture_tool(
    introspector: FakeRepoIntrospector,
    *,
    tool: str,
    arguments: Mapping[str, object],
) -> tuple[str, str]:
    """Drive the REAL tool-loop and return ``(result fed to the model, description)``.

    The loop renders the capability's dict result into the ``tool`` message as JSON (the
    real wire shape); we decode it back into its concatenated string values — the exact
    text a JSON-parsing model reconstructs — so the scenario asserts on grounded content.
    The tool's advertised description comes back too, because the owner's decision
    ("explain in words AND render") lives in that description.
    """
    registry = _registry_over(introspector)
    provider = _ToolProbeProvider(tool, arguments)
    loop = ToolLoop(provider=provider, registry=registry)
    await loop.run([{"role": "user", "content": "нарисуй архитектуру"}])
    fed_back = (
        _decode_tool_content(provider.fed_back_tool_results[0])
        if provider.fed_back_tool_results
        else ""
    )
    return fed_back, provider.offered_descriptions.get(tool, "")


def _decode_tool_content(content: str) -> str:
    """Reconstruct the model-visible text from a ``tool`` message's JSON content."""
    try:
        decoded = json.loads(content)
    except (TypeError, ValueError):
        return content
    if isinstance(decoded, dict):
        return "\n".join(str(value) for value in decoded.values())
    return str(decoded)


class _FakeRecall:
    """A duck-typed MemoryRecall: never called by the registration gate."""

    async def recall(self, query: str, *, k: int = 5) -> Sequence[object]:  # noqa: ARG002
        return []


def offered_tool_names(*, architecture_tools: bool) -> list[str]:
    """Return the tool names the REAL composition root advertises for that flag."""
    config: Mapping[str, object] = {
        "introspection": {"enabled": True, "architecture_tools": architecture_tools}
    }
    registry, _sink, _renderer = _build_registry(config, recall=_FakeRecall())  # type: ignore[arg-type]
    return [_tool_name(tool) for tool in registry.manifest()]
