# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for CapabilityRegistry — register, manifest, dispatch (GUPPI executes).

The registry is the application-side index of capabilities: it advertises them to
the model as OpenAI tool definitions (``manifest``) and runs a named one against
decoded arguments (``dispatch`` == GUPPI executes). No LLM, no network — a fake
capability records every dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.usecases.registry import CapabilityRegistry, UnknownCapabilityError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Permission


class FakeCapability:
    """A minimal Capability that records its dispatched args and returns a result."""

    def __init__(
        self,
        *,
        name: str = "recall_memory",
        description: str = "Search Bob's archived memory.",
        permission: Permission = "safe",
        result: object = "RESULT",
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema: Mapping[str, object] = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        self.permission: Permission = permission
        self._result = result
        self.calls: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        return self._result


def test_empty_registry_has_empty_manifest() -> None:
    # Arrange / Act
    registry = CapabilityRegistry()

    # Assert: no capabilities -> no tools advertised.
    assert registry.manifest() == []
    assert registry.is_empty is True


def test_register_then_manifest_yields_openai_tool_definition() -> None:
    # Arrange
    registry = CapabilityRegistry()
    cap = FakeCapability()

    # Act
    registry.register(cap)
    manifest = registry.manifest()

    # Assert: one OpenAI-shaped function tool with the capability's schema.
    assert registry.is_empty is False
    assert manifest == [
        {
            "type": "function",
            "function": {
                "name": "recall_memory",
                "description": "Search Bob's archived memory.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]


async def test_dispatch_runs_the_capability_and_returns_its_result() -> None:
    # Arrange
    registry = CapabilityRegistry()
    cap = FakeCapability(result="found it")
    registry.register(cap)

    # Act: GUPPI executes the named capability with decoded args.
    result = await registry.dispatch("recall_memory", {"query": "coffee"})

    # Assert
    assert result == "found it"
    assert cap.calls == [{"query": "coffee"}]


async def test_dispatch_unknown_capability_raises() -> None:
    # Arrange
    registry = CapabilityRegistry()

    # Act / Assert
    with pytest.raises(UnknownCapabilityError):
        await registry.dispatch("nope", {})


def test_register_duplicate_name_raises() -> None:
    # Arrange
    registry = CapabilityRegistry()
    registry.register(FakeCapability())

    # Act / Assert: names are unique (tool names must be unambiguous).
    with pytest.raises(ValueError, match="recall_memory"):
        registry.register(FakeCapability())


def test_describe_renders_a_human_manifest_for_the_system_prompt() -> None:
    # Arrange
    registry = CapabilityRegistry()
    registry.register(FakeCapability())

    # Act: the prose manifest Bob sees so he knows what GUPPI can do.
    described = registry.describe()

    # Assert
    assert "recall_memory" in described
    assert "Search Bob's archived memory." in described


def test_describe_empty_registry_is_empty_string() -> None:
    assert CapabilityRegistry().describe() == ""
