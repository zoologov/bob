# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``architecture_impact`` — «что сломается, если тронуть X» (BOB-091.1).

The skill that answers an impact question about Bob's own code: it delegates one graph
ref to the read-only :meth:`~bob.capabilities.ports.RepoIntrospector.impact` (``beadloom
why``) and returns the already-condensed answer — the node, what it depends on, what
depends on it, and how much lies deeper. The condensing is the port's pure digest, not
this layer's business; here the policy is only: validate the argument, delegate, and stay
honest when there is nothing (an unknown ref answers "не нашёл" instead of inventing
dependents, a refused ref answers with the reason instead of crashing the turn).

Read-only (``permission="safe"``) and conversation-only — never on the autonomous
safe-allowlist. Registered behind the ``introspection.architecture_tools`` sub-flag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model: one required graph ref.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"ref": {"type": "string"}},
    "required": ["ref"],
}

_DESCRIPTION = (
    "Find out what a part of Bob depends on and what depends on IT — the impact of "
    "touching it (read-only architecture graph). Pass 'ref', a graph node id such as "
    "'memory', 'capabilities' or 'bob-domain'. Use it to answer questions like «что "
    "сломается, если тронуть память?» with real dependencies instead of a guess."
)

# Honest empty-result line (US-5): an unknown ref yields nothing, and nothing is the
# answer — Bob must not invent dependents.
_NOT_FOUND = "Не нашёл такого узла в графе архитектуры."

# Fed back when the ref slot was refused before any read: the model learns the reason.
_BAD_REF = (
    "Так нельзя: 'ref' — это id узла графа (например 'memory' или 'bob-domain'), а не "
    "флаг, путь или фраза. Спроси заново с настоящим id."
)


class _ArchitectureImpactCapability:
    """Capability delegating an impact question to the RepoIntrospector port."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "architecture_impact"

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
        """Return the condensed impact of ``args['ref']``, or an honest refusal."""
        ref = args.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            return {"error": _BAD_REF}
        try:
            impact = await self._introspector.impact(ref)
        except ValueError:
            return {"error": _BAD_REF}
        return {"impact": impact if impact.strip() else _NOT_FOUND}


def make_architecture_impact_capability(
    introspector: RepoIntrospector,
) -> Capability:
    """Build the ``architecture_impact`` capability over the read-only introspector."""
    return _ArchitectureImpactCapability(introspector)
