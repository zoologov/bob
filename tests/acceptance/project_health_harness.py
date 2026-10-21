# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Project-health acceptance harness (BOB-091.2).

Drives Bob's read-only project-health tool THROUGH the boundary the BRIEF cares about —
the capability registry + the REAL
:class:`~bob.capabilities.usecases.tool_loop.ToolLoop` — and, unlike the slice-1 harness,
over the REAL :class:`SubprocessRepoIntrospector` with only the SUBPROCESS scripted.

🔴 That choice is the point: the whole value of this slice is what happens to the RAW
terminal output (48 KB of doc↔code pairs, machine porcelain, Rich frames) on its way to
the model. A harness over a fake PORT would feed the scenarios an already-digested string
— it would assert the fake's contract, which is exactly the trap this project keeps
paying for (CLAUDE.md §0.3 п.4). Here the scenario hands over the bytes beadloom really
printed, and the assertion is on what reached the model after the real argv gate, the real
digest and the real tool-loop.

The flag scenarios use the REAL composition-root gate (``_build_registry``), so "Bob never
sees the tool when the flag is off" is asserted on production wiring, not on a comment.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from bob.app import _build_registry
from bob.capabilities.adapters.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.usecases.project_health import make_project_health_capability
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.kernel.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from bob.kernel.ports import ToolDefinition, ToolLoopMessage


class ScriptedBeadloom:
    """The subprocess boundary: records argv, returns the raw stdout it was given."""

    def __init__(self, stdout: str) -> None:
        self._stdout = stdout
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        return self._stdout


class _ToolProbeProvider:
    """A ``ToolCallingProvider`` that requests ONE tool, then finalises.

    Records the tool names it was OFFERED and the ``tool`` result content fed BACK to
    it — the observable boundary the scenarios assert on.
    """

    def __init__(self, tool_name: str, arguments: Mapping[str, object]) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self._turn = 0
        self.fed_back_tool_results: list[str] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
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


def _tool_name(tool: ToolDefinition) -> str:
    function = tool.get("function", {})
    value = function.get("name", "") if isinstance(function, dict) else ""
    return str(value)


async def ask_project_health(
    repo_root: Path,
    *,
    stdout: str,
    arguments: Mapping[str, object],
) -> tuple[str, list[list[str]]]:
    """Run the tool over the REAL adapter and return ``(model-visible text, argv)``.

    ``stdout`` is what beadloom "printed"; everything after that — the argv form gate, the
    digest, the capability, the tool-loop's JSON wire shape — is production code.
    """
    runner = ScriptedBeadloom(stdout)
    introspector = SubprocessRepoIntrospector(PrivacyGuard(repo_root), runner=runner)
    registry = CapabilityRegistry()
    registry.register(make_project_health_capability(introspector))
    provider = _ToolProbeProvider("project_health", arguments)
    loop = ToolLoop(provider=provider, registry=registry)
    await loop.run([{"role": "user", "content": "как дела у проекта?"}])
    fed_back = (
        _decode_tool_content(provider.fed_back_tool_results[0])
        if provider.fed_back_tool_results
        else ""
    )
    return fed_back, runner.calls


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
