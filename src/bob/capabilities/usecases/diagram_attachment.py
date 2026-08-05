# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""DiagramAttachment — render mermaid and queue the picture for THIS turn (BOB-091.6).

ONE responsibility: turn a mermaid source into a picture WAITING to be sent in the
current turn, and say honestly whether that worked.

It is the seam ``render_diagram`` always had, extracted so a SECOND capability can use it:
``draw_architecture`` now attaches its own picture instead of asking the model to make a
follow-up ``render_diagram`` call. 🔴 That indirect route is exactly the defect this bead
closes — the live smoke showed the model receive real mermaid, retell it in words and never
make the second call, because the pairing lived only in a tool description.

Both collaborators are INJECTED and both are the shared per-turn instances:

* :class:`~bob.capabilities.ports.DiagramRenderer` — the LOCAL mermaid-cli render (no
  network; its wall-clock ceiling is the adapter's ``diagrams.timeout``). One render per
  call, never a retry, so a capability can block a turn for at most that one timeout;
* :class:`~bob.capabilities.ports.DiagramSink` — the per-turn collector the reply path
  drains to post each PNG into the turn's ``chat_id`` (the capability never sees a
  chat_id; the send stays a transport concern).

A source ALREADY queued this turn is not rendered again (dedup by normalised source, the
same key BOB-037 A uses for inline fences): two tools naming one diagram cost one render
and post ONE photo. A :class:`~bob.capabilities.ports.DiagramRenderError` (no ``mmdc``, a
timeout, malformed source) is logged and reported as ``False`` — never raised at the turn,
so Bob can say out loud that there will be no image.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.capabilities.diagrams import normalize_mermaid
from bob.capabilities.ports import DiagramRenderError, DiagramResult

if TYPE_CHECKING:
    from bob.capabilities.ports import DiagramRenderer, DiagramSink

logger = logging.getLogger(__name__)


class DiagramAttachment:
    """Render mermaid once and queue the PNG for this turn's photo send."""

    def __init__(self, renderer: DiagramRenderer, sink: DiagramSink) -> None:
        self._renderer = renderer
        self._sink = sink

    async def attach(self, mermaid: str, *, caption: str) -> bool:
        """Queue a rendered picture for ``mermaid``; ``False`` when it cannot be made.

        ``True`` means "a picture for this source is waiting to be sent this turn" —
        including the case where another tool already queued the very same source (then
        nothing is rendered twice). ``False`` means the local renderer could not produce
        it; the caller must say so honestly instead of implying an image is coming.
        """
        if self._already_queued(mermaid):
            return True
        try:
            png = await self._renderer.render(mermaid)
        except DiagramRenderError as exc:
            logger.info("diagram render failed (graceful): %s", exc)
            return False
        self._sink.push(DiagramResult(png=png, caption=caption, source=mermaid))
        return True

    def _already_queued(self, mermaid: str) -> bool:
        """Whether this very diagram is already waiting in the per-turn sink."""
        key = normalize_mermaid(mermaid)
        return any(
            normalize_mermaid(result.source) == key
            for result in self._sink.pending()
        )
