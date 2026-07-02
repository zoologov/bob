# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities-app

"""``inspect_architecture`` — the self-introspection capability over the graph.

The thin skill that lets Bob ask his OWN architecture: it delegates a graph
``ref`` to :meth:`RepoIntrospector.architecture_context` (beadloom
ctx/graph/why/search behind the .1 port) and renders the result compactly. It is
read-only (``permission="safe"``) and conversation-only — never on the autonomous
safe-allowlist. The privacy invariant lives INSIDE the port's implementation, so
this application policy only validates input, delegates, and gives an honest
"ничего не нашёл" (US-5) when the port yields nothing.

Construct it with :func:`make_inspect_architecture_capability`, passing the
introspector port; the registry then advertises it to the model and dispatches
calls to it (modelled on :mod:`bob.application.capabilities.recall_memory`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``ref`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"ref": {"type": "string"}},
    "required": ["ref"],
}

_DESCRIPTION = (
    "Inspect Bob's own architecture for a graph reference (domain / feature / "
    "component): layers, boundaries, dependencies and impact. Use this to answer "
    "questions about how Bob himself is built."
)

# Honest empty-result message (US-5): Bob never confabulates a non-existent ref.
_NOT_FOUND = "Ничего не нашёл по этой ссылке в графе архитектуры."


class _InspectArchitectureCapability:
    """Capability delegating a graph ref to the RepoIntrospector port (read-only)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "inspect_architecture"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _INPUT_SCHEMA

    @property
    def permission(self) -> Permission:
        return "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        """Return architecture context for ``args['ref']`` (honest not-found if empty)."""
        ref = args.get("ref")
        if not isinstance(ref, str):
            raise ValueError("inspect_architecture requires a string 'ref' argument")
        context = await self._introspector.architecture_context(ref)
        return {"context": context if context.strip() else _NOT_FOUND}


def make_inspect_architecture_capability(
    introspector: RepoIntrospector,
) -> Capability:
    """Build the ``inspect_architecture`` capability over the given port."""
    return _InspectArchitectureCapability(introspector)
