# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for PrivilegedRequestFulfiller — one-shot elevated fulfilment (BOB-052 .3).

The concrete :class:`PrivilegedFulfiller`: it re-runs the stored ``request_text`` AS IF
the requester were authorized — through the capability tool-loop when a provider + a
non-empty registry are wired, else through the plain router. 🔴 It only ever sees the
ONE ``request_text`` it is handed, so the elevation cannot leak to other messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.usecases.privileged_fulfiller import PrivilegedRequestFulfiller
from bob.domain.ports import ToolCallResult

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.application.router.llm_router import LLMRequest
    from bob.domain.ports import LLMMessage, Permission, ToolDefinition


class _FakeRouter:
    """Records the LLMRequests routed; returns a fixed reply."""

    def __init__(self, *, reply: str = "Вот задачи: A, B, C") -> None:
        self._reply = reply
        self.requests: list[LLMRequest] = []

    async def run(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self._reply


class _FakeToolProvider:
    """A tool-calling provider that returns a final text answer (no tool calls)."""

    def __init__(self, *, reply: str = "Вот задачи через GUPPI") -> None:
        self._reply = reply
        self.seen: list[list[LLMMessage]] = []

    async def complete_with_tools(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolDefinition]
    ) -> ToolCallResult:
        del tools
        self.seen.append(list(messages))
        return ToolCallResult(text=self._reply)


class _FakeCapability:
    """A minimal Capability for the registry (no real side effect)."""

    name = "render_diagram"
    description = "render a mermaid diagram"
    input_schema: Mapping[str, object] = {}
    permission: Permission = "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        del args
        return "ok"


def _registry_with_capability() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(_FakeCapability())
    return registry


async def test_plain_router_fulfilment_when_no_tools_wired() -> None:
    router = _FakeRouter()
    fulfiller = PrivilegedRequestFulfiller(
        router=router, registry=CapabilityRegistry(), tool_provider=None
    )

    reply = await fulfiller.fulfil(
        "покажи задачи проекта", requester_id=7, requester_name="Норман"
    )

    assert reply == "Вот задачи: A, B, C"
    assert len(router.requests) == 1
    # 🔴 Only the handed request_text reaches the model — no leak from other messages.
    assert "покажи задачи проекта" in router.requests[0].messages[-1]["content"]


async def test_tool_loop_fulfilment_when_provider_and_registry_wired() -> None:
    provider = _FakeToolProvider()
    fulfiller = PrivilegedRequestFulfiller(
        router=_FakeRouter(),
        registry=_registry_with_capability(),
        tool_provider=provider,
    )

    reply = await fulfiller.fulfil(
        "построй диаграмму", requester_id=7, requester_name="Норман"
    )

    assert reply == "Вот задачи через GUPPI"
    # The request_text was the user turn handed to the elevated tool-loop.
    assert len(provider.seen) == 1
    user_turns = [m for m in provider.seen[0] if m["role"] == "user"]
    assert any("построй диаграмму" in m["content"] for m in user_turns)
