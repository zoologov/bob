# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``draw_architecture`` — Bob draws his OWN architecture (BOB-091.1, .6).

The skill that answers "нарисуй, как ты устроен". It asks the read-only
:meth:`~bob.capabilities.ports.RepoIntrospector.architecture_diagram` for the graph, and
gives the owner BOTH halves of what he asked for: the **mermaid SOURCE** goes back to the
model so Bob explains the diagram in his own words, and the rendered **picture** is queued
for this turn's chat send by the capability itself.

🔴 **Why the capability attaches the picture** (BOB-091.6, a live-smoke defect). Until this
fix the source was ALL it returned, and the pairing "explain in words AND call
``render_diagram`` with this mermaid" lived only in the tool DESCRIPTION — an agreement with
the model. The live run: Bob called the tool, received 5 KB of real mermaid, retold it in
words accurately… and no image ever reached the owner; nothing in the RESULT pushed towards
a render and nothing structurally stopped him at words. Now the render is part of drawing:
the capability hands the source to a shared :class:`DiagramAttachment` (the same renderer +
per-turn sink ``render_diagram`` uses, so the photo travels the one proven path) and tells
the model what became of the picture. A silent PNG is still impossible — the text reply is
always the model's own words — and a second identical photo is impossible too, because the
shared sink dedups by source.

**When the render fails** (no ``mmdc``, a timeout, malformed source) the turn survives and
stays honest: the source still comes back and the answer carries an explicit "картинки не
будет" line, so Bob says so out loud instead of going quiet or implying he sent one. No
renderer wired at all (``diagrams.enabled`` off) reads the same way.

Three shapes, all read-only and all planned by the pure form planner behind the port:
no arguments — the whole-system overview; ``ref`` (+ optional ``depth``) — one node's
neighbourhood; ``internals_of`` — the C4 components inside one container. The port
reports which form it actually DREW, so when a detailed view had nothing to show (a
container-less node) this capability passes that correction on instead of letting Bob
present links as internals. An empty graph is an honest "не нашёл" and is never rendered
(a header-only diagram is a picture of nothing); a refused ref (a flag, a path, a
metacharacter) comes back as a readable error, also without a render, so the turn survives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.introspection.drawing_reply import (
    drawn_reply,
    not_found_reply,
    refused_reply,
)
from bob.capabilities.introspection.graph_form import diagram_carries_nodes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.introspection.drawing_reply import PictureStatus
    from bob.capabilities.ports import Capability, Permission, RepoIntrospector
    from bob.capabilities.usecases.diagram_attachment import DiagramAttachment

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
    "Draw Bob's own architecture graph (read-only). Call with no arguments for the "
    "whole-system overview; pass 'ref' (a graph node id such as 'memory' or "
    "'bob-domain', optionally with 'depth' 1-5) for that node's neighbourhood; pass "
    "'internals_of' for the C4 component view INSIDE one container. It returns the "
    "Mermaid SOURCE and renders the picture into the chat ITSELF — so just explain in "
    "your own words what the diagram shows; the 'picture' field of the result says "
    "whether the image is on its way, and you do NOT call render_diagram for this "
    "source (that would post the same diagram twice)."
)

# The caption sent alongside the rendered architecture PNG: Bob's own short line, in the
# project's Russian persona voice — never a system message.
_CAPTION = "Вот схема архитектуры."


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
    """Capability returning the mermaid source AND queuing the rendered picture."""

    def __init__(
        self,
        introspector: RepoIntrospector,
        attachment: DiagramAttachment | None = None,
    ) -> None:
        self._introspector = introspector
        # None = no local renderer wired (``diagrams.enabled`` off): the source still
        # reaches the model, and the answer says honestly that no picture is coming.
        self._attachment = attachment

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
        """Queue the rendered picture and return the source, or an honest refusal."""
        if _has_a_non_string_ref(args):
            return refused_reply()
        try:
            diagram = await self._introspector.architecture_diagram(
                _as_ref(args.get("ref")),
                depth=_as_depth(args.get("depth")),
                internals_of=_as_ref(args.get("internals_of")),
            )
        except ValueError:
            return refused_reply()
        if not diagram_carries_nodes(diagram.mermaid):
            # Nothing was drawn — so nothing is rendered either (no blank image, no
            # subprocess burned on a header-only diagram).
            return not_found_reply()
        return drawn_reply(
            mermaid=diagram.mermaid,
            drawn=diagram.form,
            requested=diagram.requested,
            picture=await self._attach_picture(diagram.mermaid),
        )

    async def _attach_picture(self, mermaid: str) -> PictureStatus:
        """Render + queue the picture for this turn; report what became of it.

        One render, bounded by the renderer's own ``diagrams.timeout`` (no retry), and any
        render failure comes back as ``unavailable`` rather than as an exception — so the
        picture is best-effort while the words are guaranteed.
        """
        if self._attachment is None:
            return "unavailable"
        if await self._attachment.attach(mermaid, caption=_CAPTION):
            return "sent"
        return "unavailable"


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


def make_draw_architecture_capability(
    introspector: RepoIntrospector,
    *,
    attachment: DiagramAttachment | None = None,
) -> Capability:
    """Build the ``draw_architecture`` capability over the read-only introspector.

    ``attachment`` is the shared render+queue seam (the same LOCAL renderer and per-turn
    sink ``render_diagram`` pushes into), so the picture reaches the chat by the one proven
    path. Omit it — or pass ``None`` when ``diagrams.enabled`` is off — and Bob still gets
    the source, with the answer honestly saying no image is coming.
    """
    return _DrawArchitectureCapability(introspector, attachment)
