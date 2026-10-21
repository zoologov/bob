# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tool-loop round-trip acceptance harness (BOB-069.B).

Drives the REAL :class:`~bob.capabilities.usecases.tool_loop.ToolLoop` over the REAL
``read_code`` capability (a real on-disk tree, reusing the repo-navigation harness) and
observes the FINAL reply text the loop would send to chat — never the loop's internals.

The provider (:class:`_WireProvider`) is the seam under test end to end: it does NOT hand
back hand-built :class:`ToolCallResult` objects, it PARSES canned OpenAI-compatible WIRE
bodies through the REAL :func:`~bob.infrastructure.llm.openai_compat._extract_tool_call_result`.
So the scenario exercises BOTH halves of the BOB-069 fix at once:

* the STRUCTURAL assistant turn ``ToolLoop`` builds on the re-ask (no ``[tool_calls]``
  string smuggled into ``content``), and
* the parser's defence-in-depth — turn 2 reproduces the LIVE Qwen bug, echoing a raw
  ``[tool_calls] read_code({…})`` string as its content; the real parser must recover it
  into a tool call (re-dispatch) rather than let it leak, so the loop closes to real text.

The observable outcome: a final answer carrying a REAL fact read from the file, that never
contains the raw ``[tool_calls]`` marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.infrastructure.llm.openai_compat import _extract_tool_call_result
from tests.acceptance.repo_nav_harness import GUARD_REL_PATH, build_navigator, build_repo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from bob.kernel.ports import ToolCallResult, ToolDefinition, ToolLoopMessage

# A real fact that lives in the guard file the scenario reads — its presence in the final
# reply proves the tool result actually flowed back into Bob's answer (round-trip closed).
REAL_FACT = "PrivacyGuard"

# The user's opening request (a repo question that needs the read_code tool).
USER_REQUEST = "расскажи, что за класс в privacy_guard.py"

# The raw string form the seam renders a tool intent into — the marker that must NEVER
# reach the chat as Bob's reply (BOB-069 no-leak invariant).
TOOL_CALLS_MARKER = "[tool_calls] "


def _native_call_body(query: str) -> dict[str, object]:
    """An OpenAI-native ``tool_calls`` completion body requesting ``read_code``."""
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_code",
                                "arguments": f'{{"query": "{query}"}}',
                            },
                        }
                    ],
                }
            }
        ]
    }


def _echoed_call_body(query: str) -> dict[str, object]:
    """A completion body reproducing the LIVE Qwen bug: the model ECHOES the seam's raw
    ``[tool_calls] read_code({…})`` string as plain content instead of a native call."""
    echo = f'{TOOL_CALLS_MARKER}read_code({{"query": "{query}"}})'
    return {"choices": [{"message": {"content": echo}}]}


def _final_text_body(text: str) -> dict[str, object]:
    """A plain final-answer completion body (no tools requested)."""
    return {"choices": [{"message": {"content": text}}]}


class _WireProvider:
    """A ``ToolCallingProvider`` that parses canned WIRE bodies via the REAL parser.

    Each turn pops the next canned completion body and decodes it through
    :func:`_extract_tool_call_result` — so the provider models a real MaaS endpoint's
    responses (native call, echoed-string bug, final answer), not hand-built results.
    """

    def __init__(self, bodies: Sequence[dict[str, object]]) -> None:
        self._bodies = list(bodies)
        self._turn = 0

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],  # noqa: ARG002
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        index = min(self._turn, len(self._bodies) - 1)
        self._turn += 1
        return _extract_tool_call_result(self._bodies[index])


async def run_tool_roundtrip(tmp_path: Path) -> str:
    """Boot the real ToolLoop over a real read_code capability and return the final reply.

    Turn 1 requests ``read_code`` natively; turn 2 reproduces the Qwen echo bug; turn 3
    is the clean final answer. The returned string is what Bob would send to chat.
    """
    build_repo(tmp_path)
    read_code = build_navigator(tmp_path)["read_code"]
    registry = CapabilityRegistry()
    registry.register(read_code)

    final = f"Это {REAL_FACT} — страж приватности из репозитория."
    provider = _WireProvider(
        [
            _native_call_body(GUARD_REL_PATH),
            _echoed_call_body(GUARD_REL_PATH),
            _final_text_body(final),
        ]
    )
    loop = ToolLoop(provider=provider, registry=registry)
    return await loop.run([{"role": "user", "content": USER_REQUEST}])
