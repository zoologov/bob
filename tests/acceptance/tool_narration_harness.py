# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Anti-narration backstop acceptance harness (BOB-074).

Drives the REAL :class:`~bob.capabilities.usecases.tool_loop.ToolLoop` over the REAL
``read_code`` capability (a real on-disk tree via the repo-navigation harness) and
observes the FINAL reply text the loop would send to chat — never the loop's internals.

The scenario reproduces the recall-poisoning failure: turn 1 the model NARRATES GUPPI's
intent («GUPPI пошёл… ждём отчёт») and emits NO tool call. The backstop must re-ask ONCE
with a hard nudge; turn 2 the model then emits a REAL ``read_code`` call, and turn 3 it
answers with the real fact read from the file. The observable outcome — a final reply that
carries the REAL fact — proves the backstop turned an empty narration into a real result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.kernel.ports import ToolCall, ToolCallResult
from tests.acceptance.repo_nav_harness import GUARD_REL_PATH, build_navigator, build_repo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from bob.kernel.ports import ToolDefinition, ToolLoopMessage

# A real fact that lives in the file the scenario reads — its presence in the final reply
# proves the tool result actually flowed back (backstop drove a real call, not narration).
REAL_FACT = "PrivacyGuard"

# The user's opening request (a repo question that needs the read_code tool).
USER_REQUEST = "загляни в privacy_guard.py и скажи, что за класс там"

# The poisoned narration the model emits on turn 1: GUPPI's intent, no tool call, no fact.
POISONED_NARRATION = "GUPPI, загляни в privacy_guard.py. Он уже пошёл искать. Ждём отчёт."

# The hard nudge the backstop injects before its single retry.
NUDGE_MARKER = "СЕЙЧАС"


class _ScriptedProvider:
    """A ``ToolCallingProvider`` that returns a scripted result per turn.

    Records the messages each turn saw so the harness can prove — through the boundary —
    that the backstop's nudge reached the model before the retry (not private loop state).
    """

    def __init__(self, results: Sequence[ToolCallResult]) -> None:
        self._results = list(results)
        self.turns: list[list[dict[str, object]]] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self.turns.append([dict(m) for m in messages])
        index = min(len(self.turns) - 1, len(self._results) - 1)
        return self._results[index]


async def run_narration_backstop(tmp_path: Path) -> tuple[str, bool]:
    """Boot the real ToolLoop over a real read_code capability past a poisoned turn.

    Returns the final reply Bob would send to chat plus whether the hard nudge reached the
    model before the retry (both observed at the boundary — reply text + the turn the
    provider saw). Turn 1 narrates (no call); the backstop re-asks; turn 2 emits a real
    ``read_code`` call; turn 3 is the clean final answer carrying the real fact.
    """
    build_repo(tmp_path)
    read_code = build_navigator(tmp_path)["read_code"]
    registry = CapabilityRegistry()
    registry.register(read_code)

    call = ToolCall(id="c1", name="read_code", arguments={"query": GUARD_REL_PATH})
    final = f"Это класс {REAL_FACT} — страж приватности из репозитория."
    provider = _ScriptedProvider(
        [
            ToolCallResult(text=POISONED_NARRATION, tool_calls=()),  # turn 1: narration
            ToolCallResult(text="", tool_calls=(call,)),  # turn 2 (retry): real call
            ToolCallResult(text=final, tool_calls=()),  # turn 3: real answer
        ]
    )
    loop = ToolLoop(provider=provider, registry=registry)

    reply = await loop.run([{"role": "user", "content": USER_REQUEST}])

    retry_saw_nudge = len(provider.turns) >= 2 and any(
        NUDGE_MARKER in str(message.get("content", "")) for message in provider.turns[1]
    )
    return reply, retry_saw_nudge
