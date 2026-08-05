# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``draw_architecture`` — Bob draws his OWN architecture (BOB-091.1).

The skill that answers "нарисуй, как ты устроен". It asks the read-only
:meth:`~bob.capabilities.ports.RepoIntrospector.architecture_diagram` for the graph and
returns the **mermaid SOURCE** — deliberately not a picture.

**Why source and not an image** (the owner's decision): with the source in hand Bob can
say IN WORDS what the diagram shows *and* hand the very same source to the existing
``render_diagram`` skill, which renders it locally and posts the image. Returning a PNG
here would mean Bob silently dropping a picture with nothing to say about it — and would
duplicate a render seam that already works. The tool description therefore names that
pairing explicitly, because the model is what connects the two calls.

Three shapes, all read-only and all planned by the pure form planner behind the port:
no arguments — the whole-system overview; ``ref`` (+ optional ``depth``) — one node's
neighbourhood; ``internals_of`` — the C4 components inside one container. The port
reports which form it actually DREW, so when a detailed view had nothing to show (a
container-less node) this capability passes that correction on instead of letting Bob
present links as internals. An empty graph is an honest "не нашёл", never a blank
picture; a refused ref (a flag, a path, a metacharacter) comes back as a readable error
so the turn survives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.introspection.graph_form import diagram_carries_nodes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model. NOTHING is required: the argument-free call is the
# whole-system overview, which is what "нарисуй архитектуру" usually means.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "ref": {"type": "string"},
        "depth": {"type": "integer"},
        "internals_of": {"type": "string"},
    },
}

_DESCRIPTION = (
    "Get the Mermaid SOURCE of Bob's own architecture graph (read-only). Call with no "
    "arguments for the whole-system overview; pass 'ref' (a graph node id such as "
    "'memory' or 'bob-domain', optionally with 'depth' 1-5) for that node's "
    "neighbourhood; pass 'internals_of' for the C4 component view INSIDE one container. "
    "It returns diagram SOURCE, not an image — so do BOTH: explain in your own words "
    "what the diagram shows, and call render_diagram with this exact mermaid string to "
    "send the picture to the chat."
)

# Honest empty-result line: an unresolved ref yields a header-only diagram, i.e. a
# picture of nothing. Bob says so instead of rendering a blank image.
_NOT_FOUND = (
    "Не нашёл такого узла в графе архитектуры — скажи об этом честно и предложи "
    "общую схему (вызов без аргументов)."
)

# Fed back when the DETAILED view had nothing to draw and the port degraded to the
# node's links, so the model never passes one view off as the other.
_FALLBACK_NOTE = (
    "У этого узла в графе нет внутренностей (он не контейнер) — это схема его связей. "
    "Скажи об этом честно."
)

# Fed back when a slot was refused before any read (a flag / path / metacharacter, or a
# non-string value): the model gets the reason and can retry with a real ref-id.
_BAD_REF = (
    "Так нельзя: 'ref'/'internals_of' — это id узла графа (например 'memory' или "
    "'bob-domain'), а не флаг или путь. Попроси схему заново с настоящим id."
)


def _as_depth(raw: object) -> int | None:
    """Read a traversal depth from a model-supplied value, or ``None``.

    A model routinely sends ``"2"`` where the schema says integer, so a digit string is
    accepted; anything else (prose, a float, ``None``) yields ``None`` — "no depth
    asked" — rather than a guessed number. Bounds are the port's job.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _as_ref(raw: object) -> str | None:
    """Read a ref slot: a non-blank string, or ``None`` when it was not asked for."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw


class _DrawArchitectureCapability:
    """Capability returning the mermaid source of Bob's architecture (read-only)."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "draw_architecture"

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
        """Return the mermaid source (plus which form it is), or an honest refusal."""
        if _has_a_non_string_ref(args):
            return {"error": _BAD_REF}
        try:
            diagram = await self._introspector.architecture_diagram(
                _as_ref(args.get("ref")),
                depth=_as_depth(args.get("depth")),
                internals_of=_as_ref(args.get("internals_of")),
            )
        except ValueError:
            return {"error": _BAD_REF}
        if not diagram_carries_nodes(diagram.mermaid):
            return {"error": _NOT_FOUND}
        result: dict[str, object] = {
            "mermaid": diagram.mermaid,
            "form": diagram.form,
        }
        if diagram.form != diagram.requested:
            result["note"] = _FALLBACK_NOTE
        return result


def _has_a_non_string_ref(args: Mapping[str, object]) -> bool:
    """Whether a ref slot holds something that is not a string at all (e.g. ``42``).

    An absent key means "not asked" (the overview is a legitimate call) and a blank
    string means the same; a number or an object is a MALFORMED request and must not be
    silently read as "no ref", or Bob would answer a question nobody asked.
    """
    return any(
        key in args and args[key] is not None and not isinstance(args[key], str)
        for key in ("ref", "internals_of")
    )


def make_draw_architecture_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``draw_architecture`` capability over the read-only introspector."""
    return _DrawArchitectureCapability(introspector)
