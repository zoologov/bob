# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``render_diagram`` — render mermaid to a LOCAL PNG and send it as a photo (BOB-035).

The skill that lets Bob draw: it takes a single ``mermaid`` string (the diagram
source Bob or the user wrote), renders it to a PNG LOCALLY via the injected
:class:`~bob.capabilities.ports.DiagramRenderer` (no external service — privacy), and hands
the result to the reply path to send as a Telegram photo.

**The photo-send seam.** A capability normally returns TEXT to the tool-loop, but the
PNG must reach the CURRENT chat — whose ``chat_id`` lives per-turn in
``HandleMessage``, not in the global registry. So the capability does NOT send the
photo itself: it pushes a structured :class:`~bob.capabilities.ports.DiagramResult` (PNG +
caption) into a per-turn :class:`~bob.capabilities.ports.DiagramSink` and returns a short
TEXT confirmation. After the tool-loop, the reply path (which holds the ``chat_id``
and the gateway) drains the sink and sends each diagram as a photo. This keeps the
chat_id strictly per-turn and the send a transport concern — DDD layering intact (the
domain port renders, infra does the I/O, the gateway sends).

The render + push itself lives in the shared
:class:`~bob.capabilities.usecases.diagram_attachment.DiagramAttachment` (BOB-091.6), so
``draw_architecture`` can attach its OWN picture down the very same path instead of asking
the model for a follow-up call here — and a diagram already queued this turn is never
rendered (or posted) twice.

It is ``permission="safe"`` (local, read-nothing) and renders ONLY its INPUT — it
reads no personal data (memory / soul / config), so it can never leak Bob's private
world. Construct it with :func:`make_render_diagram_capability`. On a render failure
(``mmdc`` absent / malformed source / timeout) it degrades to an honest "renderer
unavailable" text and never crashes the turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.usecases.diagram_attachment import DiagramAttachment

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.ports import (
        Capability,
        DiagramRenderer,
        DiagramResult,
        DiagramSink,
        Permission,
    )

# JSON-Schema advertised to the model so it knows the single ``mermaid`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"mermaid": {"type": "string"}},
    "required": ["mermaid"],
}

_DESCRIPTION = (
    "Render a Mermaid diagram and send it to the chat as an image. Pass the Mermaid "
    "source you wrote (e.g. a 'graph TD; A-->B' flowchart, a sequence or class "
    "diagram) and Bob renders it to a PNG LOCALLY and posts it as a photo (tap to "
    "zoom). It renders ONLY the Mermaid you give it — it reads no personal data, "
    "memory, or private state."
)

# Short caption sent alongside the rendered photo. Russian persona voice (project
# language) — a brief, in-character line, never a system message.
_CAPTION = "Вот диаграмма."

# Text confirmation fed back to the tool-loop (the model never sees the bytes): it
# tells the model the diagram has been posted, so it does not try to re-send it.
_CONFIRMATION = "Diagram rendered and sent to the chat as an image."

# Honest failure line fed back to the tool-loop when the local renderer is
# unavailable, so Bob can say so in his reply instead of crashing the turn.
_RENDERER_UNAVAILABLE = (
    "The diagram renderer is unavailable (mermaid-cli not installed or it failed); "
    "tell the user you could not render the image."
)


class CollectingDiagramSink:
    """An in-memory per-turn :class:`~bob.capabilities.ports.DiagramSink` (push then drain).

    The simplest correct collector: the capability :meth:`push`es each rendered
    diagram; the reply path :meth:`drain`s them all (returning them and clearing the
    buffer) and sends each as a photo. ``drain`` clears the buffer so every turn
    starts empty — no diagram leaks from one turn into the next.
    """

    def __init__(self) -> None:
        self._pending: list[DiagramResult] = []

    def push(self, result: DiagramResult) -> None:
        """Record one rendered diagram for the reply path to send this turn."""
        self._pending.append(result)

    def pending(self) -> tuple[DiagramResult, ...]:
        """Return the diagrams collected so far WITHOUT clearing them (BOB-037).

        A non-destructive peek the inline-mermaid auto-render reads to dedup against
        a diagram the ``render_diagram`` tool already rendered this turn (by source)
        before pushing its own; :meth:`drain` still does the clearing send.
        """
        return tuple(self._pending)

    def drain(self) -> tuple[DiagramResult, ...]:
        """Return + clear the diagrams collected this turn (empty when none)."""
        drained = tuple(self._pending)
        self._pending.clear()
        return drained


class _RenderDiagramCapability:
    """Capability rendering mermaid to a PNG and queuing it for a photo send."""

    def __init__(self, renderer: DiagramRenderer, sink: DiagramSink) -> None:
        # The shared render+queue seam (BOB-091.6): the same collaborator
        # ``draw_architecture`` attaches its own picture with, so BOTH tools travel one
        # proven path and a diagram already queued this turn is never rendered twice.
        self._attachment = DiagramAttachment(renderer, sink)

    @property
    def name(self) -> str:
        return "render_diagram"

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
        """Render ``args['mermaid']`` locally, queue the photo, confirm to the loop."""
        mermaid = args.get("mermaid")
        if not isinstance(mermaid, str):
            raise ValueError("render_diagram requires a string 'mermaid' argument")
        if await self._attachment.attach(mermaid, caption=_CAPTION):
            return {"status": _CONFIRMATION}
        return {"error": _RENDERER_UNAVAILABLE}


def make_render_diagram_capability(
    renderer: DiagramRenderer, sink: DiagramSink
) -> Capability:
    """Build the ``render_diagram`` capability over the renderer + per-turn sink."""
    return _RenderDiagramCapability(renderer, sink)
