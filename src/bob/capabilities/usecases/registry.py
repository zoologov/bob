# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""CapabilityRegistry — advertise capabilities to the model, dispatch them (GUPPI).

GUPPI's index of what Bob can do. It is deliberately the *seam*, not the plugin
machinery (sandboxing / discovery / self-creation come later behind this same
contract):

* :meth:`register` — add a :class:`~bob.capabilities.ports.Capability` (unique name).
* :meth:`manifest` — render the registered capabilities as OpenAI ``tools``
  definitions to hand the LLM, so the model can request them.
* :meth:`dispatch` — run a named capability against decoded arguments. This is
  the execution side: **GUPPI executes** the skill the model asked for.
* :meth:`describe` — a short prose listing for Bob's system prompt, so he *knows*
  what GUPPI can do (referenced in his persona).
* :meth:`permission_of` — what a capability declares about needing a human's go-ahead;
  read by :class:`SafeCapabilityDispatcher`, the autonomous boundary.

This is pure application policy: it holds the capability objects (whose concrete
side-effects live behind their own ports) and never touches transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission
    from bob.kernel.ports import ToolDefinition


class UnknownCapabilityError(LookupError):
    """Raised when dispatch is asked for a capability that was never registered."""


class CapabilityNotAllowedError(LookupError):
    """Raised when the safe dispatcher is asked for a capability off its allowlist."""


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

    def permission_of(self, name: str) -> Permission | None:
        """The named capability's declared permission, or ``None`` if unregistered.

        The read side of the ``permission`` seam: an unknown name has no declaration at
        all, and the caller must treat that as «не разрешено», never as «safe».
        """
        capability = self._capabilities.get(name)
        return None if capability is None else capability.permission


class SafeCapabilityDispatcher:
    """An allowlist-restricted view over a registry — the autonomous safe boundary.

    The hard boundary for the self-directed tick (BOB-015 .3): it wraps a
    :class:`CapabilityRegistry` but exposes EXCLUSIVELY the intersection of the
    registry and an explicit safe-allowlist (``goals.safe_capabilities``). A
    capability outside the allowlist is unreachable — :meth:`allows` returns
    ``False`` and :meth:`dispatch` raises :class:`CapabilityNotAllowedError` — so an
    external-agency or arbitrary capability can NEVER be executed on the autonomous
    path by construction, no matter what the registry holds. An empty allowlist
    means nothing is runnable autonomously (the conservative default).

    🔴 The SECOND condition is the capability's own ``permission`` (BOB-090.B-fix): a
    ``"confirm"`` capability declares that a human must clear it before it runs, and on
    the self-directed tick there IS no human to ask — so it is refused even when someone
    put it on the allowlist. This is what makes the declaration load-bearing: it was read
    by nobody, and a decorative gate is worse than an absent one, because it reads as
    protection (``send_to_chat`` — visible to other people and irreversible — is the
    capability that actually stands behind it). The declaration lives WITH the capability,
    so a new skill is gated by what it says about itself, not by remembering a list.
    """

    def __init__(self, registry: CapabilityRegistry, *, allowlist: tuple[str, ...]) -> None:
        self._registry = registry
        self._allowlist = frozenset(allowlist)

    def allows(self, name: str) -> bool:
        """Whether ``name`` is allow-listed AND declares itself safe to run unattended.

        An unregistered name (no declaration at all) is never allowed: doubt refuses.
        """
        return name in self._allowlist and self._registry.permission_of(name) == "safe"

    async def dispatch(self, name: str, args: Mapping[str, object]) -> object:
        """Run the named capability ONLY if allow-listed; raise otherwise."""
        if not self.allows(name):
            raise CapabilityNotAllowedError(
                f"capability not on the autonomous safe-allowlist: {name}"
            )
        return await self._registry.dispatch(name, args)


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
