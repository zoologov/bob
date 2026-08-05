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

from bob.capabilities.usecases.registry import (
    CapabilityNotAllowedError,
    CapabilityRegistry,
    SafeCapabilityDispatcher,
    UnknownCapabilityError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Permission


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

    # Act / Assert: имя невыполнимой capability названо в ошибке (иначе лог немой).
    with pytest.raises(UnknownCapabilityError, match="nope"):
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
    registry.register(FakeCapability(name="web_search", description="Search the web."))

    # Act: the prose manifest Bob sees so he knows what GUPPI can do.
    described = registry.describe()

    # Assert: одна capability — одна строка (перечень, не слипшийся абзац).
    assert described == (
        "- recall_memory: Search Bob's archived memory.\n- web_search: Search the web."
    )


def test_describe_empty_registry_is_empty_string() -> None:
    assert CapabilityRegistry().describe() == ""


# --- permission: «confirm» и автономная граница (BOB-090.B-fix) ---------------------
# 🔴 Поле ``permission`` объявлялось «швом будущего гейта» и не читалось НИКЕМ: защита,
# которой нет, но которая создаёт ощущение, что она есть. Настоящий читатель — автономная
# граница: на самодвижущемся тике человека, который подтвердит действие, попросту нет.


def test_a_confirm_capability_is_never_autonomous_even_when_allowlisted() -> None:
    registry = CapabilityRegistry()
    registry.register(FakeCapability(name="send_to_chat", permission="confirm"))
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("send_to_chat",))

    # Ошибка в конфиге не превращает необратимое действие в автономное.
    assert dispatcher.allows("send_to_chat") is False


async def test_a_confirm_capability_is_refused_at_autonomous_dispatch() -> None:
    registry = CapabilityRegistry()
    cap = FakeCapability(name="send_to_chat", permission="confirm")
    registry.register(cap)
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("send_to_chat",))

    with pytest.raises(CapabilityNotAllowedError, match="send_to_chat"):
        await dispatcher.dispatch("send_to_chat", {"query": "привет"})
    assert cap.calls == []  # исполнения не произошло (не «прошло, но без записи»)


async def test_a_safe_allowlisted_capability_still_runs_autonomously() -> None:
    # Обратная сторона: гейт не глушит автономию вообще — только «confirm».
    registry = CapabilityRegistry()
    cap = FakeCapability(permission="safe", result="ok")
    registry.register(cap)
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("recall_memory",))

    assert dispatcher.allows("recall_memory") is True
    assert await dispatcher.dispatch("recall_memory", {"query": "кофе"}) == "ok"
    # Аргументы доезжают до capability в том же виде, не теряясь по дороге.
    assert cap.calls == [{"query": "кофе"}]


def test_an_unregistered_name_is_not_allowed_by_the_allowlist_alone() -> None:
    # Разрешение спрашивают саму capability; одного имени в списке мало.
    dispatcher = SafeCapabilityDispatcher(CapabilityRegistry(), allowlist=("ghost",))

    assert dispatcher.allows("ghost") is False
