# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""CapabilityRegistry — advertise capabilities to the model, dispatch them (GUPPI).

GUPPI's index of what Bob can do. It is deliberately the *seam*, not the plugin
machinery (sandboxing / discovery / self-creation come later behind this same
contract):

* :meth:`register` — add a :class:`~bob.domain.ports.Capability` (unique name).
* :meth:`manifest` — render the registered capabilities as OpenAI ``tools``
  definitions to hand the LLM, so the model can request them.
* :meth:`dispatch` — run a named capability against decoded arguments. This is
  the execution side: **GUPPI executes** the skill the model asked for.
* :meth:`describe` — a short prose listing for Bob's system prompt, so he *knows*
  what GUPPI can do (referenced in his persona).

This is pure application policy: it holds the capability objects (whose concrete
side-effects live behind their own ports) and never touches transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, ToolDefinition


class UnknownCapabilityError(LookupError):
    """Raised when dispatch is asked for a capability that was never registered."""


class CapabilityRegistry:
    """An ordered, name-unique index of capabilities GUPPI can advertise and run."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    @property
    def is_empty(self) -> bool:
        """Whether no capabilities are registered (the default, today's behaviour)."""
        return not self._capabilities

    def register(self, capability: Capability) -> None:
        """Add ``capability`` to the registry; its name must be unique."""
        name = capability.name
        if name in self._capabilities:
            raise ValueError(f"capability already registered: {name}")
        self._capabilities[name] = capability

    def manifest(self) -> list[ToolDefinition]:
        """Render every capability as an OpenAI ``tools`` function definition."""
        return [_tool_definition(cap) for cap in self._capabilities.values()]

    async def dispatch(self, name: str, args: Mapping[str, object]) -> object:
        """Execute the named capability against ``args`` (GUPPI executes)."""
        capability = self._capabilities.get(name)
        if capability is None:
            raise UnknownCapabilityError(f"unknown capability: {name}")
        return await capability.execute(args)

    def describe(self) -> str:
        """Render a short prose manifest of capabilities for Bob's system prompt."""
        lines = [
            f"- {cap.name}: {cap.description}" for cap in self._capabilities.values()
        ]
        return "\n".join(lines)


def _tool_definition(capability: Capability) -> ToolDefinition:
    """Map one capability onto its OpenAI function-tool definition."""
    return {
        "type": "function",
        "function": {
            "name": capability.name,
            "description": capability.description,
            "parameters": dict(capability.input_schema),
        },
    }
