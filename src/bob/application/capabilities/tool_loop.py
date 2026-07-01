# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ToolLoop — drive the model<->tools round-trip until a final answer.

GUPPI's tool-use loop, the act side of the capability seam. Given a seeded
conversation and the registry manifest, it:

1. asks the :class:`~bob.domain.ports.ToolCallingProvider` to complete the turn,
   offering the registered capabilities as ``tools``;
2. if the model requested tool calls, **dispatches** each through the registry
   (GUPPI executes), appends the assistant turn and a ``tool`` result message,
   and re-asks — looping until the model returns a final text answer;
3. caps the number of turns so a model that never finalises cannot run away.

An unknown tool is not fatal: the error is fed back as the tool result so the
model can recover, mirroring how a real tool failure would surface. This is pure
application policy; the capabilities' side effects live behind their own ports.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from bob.application.capabilities.registry import UnknownCapabilityError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.capabilities.progress_announcer import ProgressAnnouncer
    from bob.application.capabilities.registry import CapabilityRegistry
    from bob.domain.ports import LLMMessage, ToolCall, ToolCallingProvider

logger = logging.getLogger(__name__)

# Default ceiling on model turns in one loop: enough for a couple of tool hops,
# low enough that a model stuck requesting tools cannot loop forever.
_DEFAULT_MAX_TURNS = 6


class ToolLoop:
    """Run the model<->capability tool-use loop to a final text answer."""

    def __init__(
        self,
        *,
        provider: ToolCallingProvider,
        registry: CapabilityRegistry,
        max_turns: int = _DEFAULT_MAX_TURNS,
        announcer: ProgressAnnouncer | None = None,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        self._provider = provider
        self._registry = registry
        self._max_turns = max_turns
        self._announcer = announcer

    async def run(self, messages: Sequence[LLMMessage]) -> str:
        """Complete ``messages`` through the tool-loop and return the final text."""
        tools = self._registry.manifest()
        conversation: list[LLMMessage] = list(messages)
        for _ in range(self._max_turns):
            result = await self._provider.complete_with_tools(conversation, tools=tools)
            if not result.tool_calls:
                return result.text
            conversation.append(_assistant_turn(result.tool_calls))
            for call in result.tool_calls:
                conversation.append(await self._run_tool(call))
        logger.warning("Tool loop hit the turn cap (%d) without a final answer", self._max_turns)
        return ""

    async def _run_tool(self, call: ToolCall) -> LLMMessage:
        """Dispatch one tool call (GUPPI executes) and render its ``tool`` message."""
        # Interim "searching…" line (BOB-055): before a SLOW capability runs, let the
        # announcer say a live word in Bob's voice so the owner is not left in silence.
        # Decorative and by-name — the announcer stays silent for fast skills and
        # swallows its own errors, so it never delays or breaks the dispatch below.
        if self._announcer is not None:
            await self._announcer.announce(call.name)
        try:
            result = await self._registry.dispatch(call.name, call.arguments)
        except UnknownCapabilityError:
            content = f"error: unknown capability '{call.name}'"
        except Exception:  # a tool failure must not crash the turn
            logger.exception("Capability %s failed during dispatch", call.name)
            content = f"error: capability '{call.name}' failed"
        else:
            content = _render_result(result)
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": content,
        }


def _assistant_turn(tool_calls: Sequence[ToolCall]) -> LLMMessage:
    """Render the assistant turn that requested ``tool_calls`` (OpenAI shape).

    The content is serialised so the seam carries the assistant's tool intent in
    the conversation even on providers that echo it back as plain text.
    """
    rendered = ", ".join(f"{call.name}({json.dumps(dict(call.arguments))})" for call in tool_calls)
    return {"role": "assistant", "content": f"[tool_calls] {rendered}"}


def _render_result(result: object) -> str:
    """Render a capability result into the textual ``tool`` message content."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except (TypeError, ValueError):
        return str(result)
