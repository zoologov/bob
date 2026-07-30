# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""ToolLoop — drive the model<->tools round-trip until a final answer.

GUPPI's tool-use loop, the act side of the capability seam. Given a seeded
conversation and the registry manifest, it:

1. asks the :class:`~bob.capabilities.ports.ToolCallingProvider` to complete the turn,
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

from bob.capabilities.usecases.registry import UnknownCapabilityError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.capabilities.ports import ToolCall, ToolCallingProvider
    from bob.capabilities.usecases.progress_announcer import ProgressAnnouncer
    from bob.capabilities.usecases.registry import CapabilityRegistry
    from bob.kernel.ports import ToolLoopMessage

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

    async def run(self, messages: Sequence[ToolLoopMessage]) -> str:
        """Complete ``messages`` through the tool-loop and return the final text."""
        tools = self._registry.manifest()
        conversation: list[ToolLoopMessage] = list(messages)
        for _ in range(self._max_turns):
            result = await self._provider.complete_with_tools(conversation, tools=tools)
            if not result.tool_calls:
                return result.text
            conversation.append(_assistant_turn(result.tool_calls))
            for call in result.tool_calls:
                conversation.append(await self._run_tool(call))
        logger.warning("Tool loop hit the turn cap (%d) without a final answer", self._max_turns)
        return ""

    async def _run_tool(self, call: ToolCall) -> ToolLoopMessage:
        """Dispatch one tool call (GUPPI executes) and render its ``tool`` message."""
        # Interim "searching…" line (BOB-055): before a SLOW capability runs, let the
        # announcer say a live word in Bob's voice so the owner is not left in silence.
        # Decorative and by-name — the announcer stays silent for fast skills. The seam
        # does NOT trust the announcer to be well-behaved: any error here is swallowed so
        # a decorative interim line can NEVER delay or break the dispatch below (review .4).
        if self._announcer is not None:
            try:
                await self._announcer.announce(call.name, call.arguments)
            except Exception:  # decorative: an announcer fault must not touch the turn
                logger.exception("progress announce failed for %s; ignoring", call.name)
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


def _assistant_turn(tool_calls: Sequence[ToolCall]) -> ToolLoopMessage:
    """Render the assistant turn that requested ``tool_calls`` (OpenAI-native shape).

    Carries the tool intent in the STRUCTURAL ``tool_calls`` array the OpenAI schema
    defines — NOT as a ``[tool_calls] …`` string smuggled into ``content`` (BOB-069).
    The old string form left the re-ask malformed (an assistant turn with no
    ``tool_calls``, a ``tool`` result referencing an ``id`` absent from the history),
    so Qwen echoed the string back verbatim and it leaked into the chat. Here each
    call becomes ``{"id","type":"function","function":{"name","arguments"}}`` with
    ``arguments`` a JSON STRING (as OpenAI expects) and ``id`` matching the
    ``tool_call_id`` :meth:`ToolLoop._run_tool` puts on the result — so the model
    binds each ``tool`` result to its call and drives on to a final text answer.
    """
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(dict(call.arguments)),
                },
            }
            for call in tool_calls
        ],
    }


def _render_result(result: object) -> str:
    """Render a capability result into the textual ``tool`` message content."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except (TypeError, ValueError):
        return str(result)
