# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-110: a failing tool must say WHY, and the loop must never answer with silence.

Both guards come from one live incident (2026-08-18, group). Asked to show the
architecture on a host where the ``beadloom`` binary was missing, Bob:

* was told by this seam only ``error: capability 'draw_architecture' failed`` — the
  reason (``[Errno 2] No such file or directory: 'beadloom'``) was recorded into his
  first-person diary and **dropped** from the tool result. Having no cause to report,
  he invented one ("GUPPI decided «show» was too abstract and froze"), which also
  broke the GUPPI canon (BOB-096). The fabrication was not a model whim: this seam
  handed him a vacuum;
* then answered the follow-up with an EMPTY message — the loop returned ``""`` after
  exhausting its turns, so the owner got a blank line and the conversation died.

These are asserted through the loop's OBSERVABLE output (what reaches the model, what
reaches the user), never through private state — a failure that is invisible at the
boundary is exactly what made the incident possible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import NO_ANSWER_REPLY, ToolLoop
from bob.kernel.ports import ToolCall, ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.capabilities.ports import Permission
    from bob.kernel.ports import ToolDefinition, ToolLoopMessage

_MISSING_BINARY = "[Errno 2] No such file or directory: 'beadloom'"


class _MissingToolCapability:
    """Stands in for the introspector shelling a binary that is absent in prod."""

    name = "draw_architecture"
    description = "Draw the architecture diagram."
    input_schema: Mapping[str, object] = {"type": "object", "properties": {}}
    permission: Permission = "safe"

    async def execute(self, args: Mapping[str, object]) -> object:  # noqa: ARG002
        raise FileNotFoundError(2, "No such file or directory", "beadloom")


class _AlwaysCallsProvider:
    """Never produces a final answer — it only ever asks for the tool again."""

    def __init__(self) -> None:
        self.turns: list[list[dict[str, object]]] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        call = ToolCall(id=f"c{len(self.turns)}", name="draw_architecture", arguments={})
        return ToolCallResult(text="", tool_calls=(call,))

    @property
    def all_text(self) -> str:
        return "\n".join(str(m.get("content", "")) for turn in self.turns for m in turn)


def _registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(_MissingToolCapability())
    return registry


def _seed() -> list[ToolLoopMessage]:
    return [{"role": "user", "content": "покажи нашу актуальную архитектуру"}]


async def test_a_failing_tool_tells_the_model_why_it_failed() -> None:
    # Arrange: the tool fails the way it failed in production — a missing binary.
    provider = _AlwaysCallsProvider()
    loop = ToolLoop(provider=provider, registry=_registry(), max_turns=2)

    # Act
    await loop.run(_seed())

    # Assert: the REASON reaches the model, not just the fact of failure. Without it
    # Bob cannot answer honestly — and in production he filled the gap by inventing.
    assert "error: capability 'draw_architecture' failed" in provider.all_text
    assert _MISSING_BINARY in provider.all_text, (
        "the tool result must carry WHY the tool failed; with only 'failed' Bob has no "
        "cause to report and confabulates one (BOB-110)"
    )


async def test_the_loop_never_answers_with_silence() -> None:
    # Arrange: the model never returns a final answer, so the turn cap is reached —
    # the exact shape of the live incident's second message.
    provider = _AlwaysCallsProvider()
    loop = ToolLoop(provider=provider, registry=_registry(), max_turns=2)

    # Act
    answer = await loop.run(_seed())

    # Assert: an answer that is empty (or blank) is what the owner actually received.
    assert answer.strip(), "running out of turns must not send the owner a blank message"
    assert answer == NO_ANSWER_REPLY


async def test_the_silence_reply_admits_failure_without_inventing_a_cause() -> None:
    """The honest wording is part of the contract, not decoration.

    It must read as Bob failing, not as an explanation of WHY — inventing a cause is
    the very defect this bead is about, so the fallback may not carry one.
    """
    assert NO_ANSWER_REPLY.strip()
    assert "GUPPI" not in NO_ANSWER_REPLY, (
        "the fallback must not narrate GUPPI — that breaks the canon (BOB-096) and is "
        "how the live confabulation was phrased"
    )
