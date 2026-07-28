# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""DiagramSender — auto-render inline mermaid + send the per-turn queued diagrams.

The turn's diagram concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 1, behavior-preserving):

* :meth:`autorender_inline_mermaid` renders any fenced ```mermaid blocks the model
  wrote into its TEXT reply (BOB-037 A — the reliability fix), queues each to the
  per-turn sink deduped against what the ``render_diagram`` tool already queued, and
  strips the rendered fences from the visible reply (the image replaces them); and
* :meth:`send_pending` drains the per-turn :class:`~bob.capabilities.ports.DiagramSink`
  and posts each rendered PNG into the turn's ``chat_id`` via the gateway, in the
  configured send mode (``document`` uncompressed / ``photo`` inline preview).

🔴 The ``sink`` is the SAME per-turn instance the ``render_diagram`` capability pushes
into inside the registry's tool-loop — it is INJECTED here (never constructed), so the
push (capability) and the drain (this sender) act on one object. Unwired renderer / no
sink → a clean no-op, so the turn behaves exactly as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Protocol

from bob.capabilities.diagrams import (
    extract_mermaid_blocks,
    normalize_mermaid,
    strip_mermaid_blocks,
)
from bob.capabilities.ports import DiagramRenderError, DiagramResult

if TYPE_CHECKING:
    from bob.capabilities.ports import DiagramRenderer, DiagramSink

logger = logging.getLogger(__name__)

# How a rendered diagram is sent (BOB-037 C). ``document`` posts the PNG as an
# UNCOMPRESSED file (full resolution, tap → real pixels) — the product default, since
# Telegram ``send_photo`` recompresses to JPEG and caps the long side (~1280px), which
# makes a dense diagram unreadable. ``photo`` keeps the inline-preview photo.
type DiagramSendMode = Literal["document", "photo"]
_DEFAULT_DIAGRAM_SEND_AS: DiagramSendMode = "document"

# The short caption sent alongside an auto-rendered inline diagram (BOB-037 A): Bob's
# in-character Russian line, mirroring the render_diagram tool's caption.
_INLINE_DIAGRAM_CAPTION = "Вот диаграмма."


class DiagramGateway(Protocol):
    """The transport seam DiagramSender needs: post a PNG as a photo or a document.

    Structurally satisfied by HandleMessage's ``ReplyGateway`` — the sender depends on
    this narrow port, never on the Telegram transport (or the application use-case).
    """

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None: ...

    async def send_document(
        self, *, chat_id: int, document: bytes, caption: str | None = None
    ) -> None: ...


class DiagramSender:
    """Auto-render inline mermaid + send the diagrams queued this turn (BOB-035/037)."""

    def __init__(
        self,
        *,
        gateway: DiagramGateway,
        diagram_sink: DiagramSink | None,
        diagram_renderer: DiagramRenderer | None,
        diagram_send_as: DiagramSendMode = _DEFAULT_DIAGRAM_SEND_AS,
    ) -> None:
        self._gateway = gateway
        # 🔴 The SHARED per-turn sink: the same instance the render_diagram capability
        # pushes into inside the registry's tool-loop. Injected, never constructed here.
        self._diagram_sink = diagram_sink
        self._diagram_renderer = diagram_renderer
        self._diagram_send_as: DiagramSendMode = diagram_send_as

    async def autorender_inline_mermaid(self, reply: str) -> str:
        """Render fenced ```mermaid blocks in ``reply`` and strip them (BOB-037 A).

        The reliability fix: the model usually writes the mermaid as a fenced block in
        its TEXT reply instead of calling the render_diagram tool. Each fenced block is
        rendered via the wired renderer and queued to the same per-turn sink, and the
        fence is stripped from the visible reply (the image replaces it). A block whose
        source the render_diagram tool ALREADY rendered this turn is skipped (dedup by
        normalised source) so the same diagram is never sent twice. A
        :class:`DiagramRenderError` leaves that block AS text (graceful — no crash);
        unwired renderer / no sink / no fenced block → the reply is returned unchanged.
        """
        if self._diagram_renderer is None or self._diagram_sink is None:
            return reply
        blocks = extract_mermaid_blocks(reply)
        if not blocks:
            return reply
        # Sources the render_diagram TOOL already queued this turn — dedup keys so the
        # same diagram is never rendered/sent twice. They count as "handled" (stripped).
        handled = {
            normalize_mermaid(result.source)
            for result in self._diagram_sink.pending()
        }
        for source in blocks:
            key = normalize_mermaid(source)
            if key in handled:
                continue  # the tool already queued it; just strip the echoed fence
            if await self._render_inline_block(source):
                handled.add(key)
        # Strip ONLY the blocks that were rendered or deduped; a block whose render
        # failed stays as text so Bob still answers (graceful).
        return strip_mermaid_blocks(reply, only=handled)

    async def _render_inline_block(self, source: str) -> bool:
        """Render one inline mermaid ``source`` and queue it; ``False`` on failure (BOB-037).

        Renders via the wired renderer and pushes a :class:`DiagramResult` (carrying the
        source for dedup) onto the per-turn sink. A :class:`DiagramRenderError` (mmdc
        missing / malformed) is logged and swallowed and returns ``False`` so the caller
        leaves the fence as text.
        """
        assert self._diagram_renderer is not None  # guarded by the caller
        assert self._diagram_sink is not None  # guarded by the caller
        try:
            png = await self._diagram_renderer.render(source)
        except DiagramRenderError as exc:
            logger.info("inline mermaid render failed (graceful): %s", exc)
            return False
        self._diagram_sink.push(
            DiagramResult(png=png, caption=_INLINE_DIAGRAM_CAPTION, source=source)
        )
        return True

    async def send_pending(self, chat_id: int) -> None:
        """Post the diagrams queued this turn (BOB-035 + BOB-037 C).

        Drains the per-turn :class:`~bob.capabilities.ports.DiagramSink` (cleared so the
        next turn starts empty) and sends each rendered PNG into ``chat_id`` via the
        gateway — keeping the chat_id strictly per-turn and the send a transport
        concern. The send MODE is config-driven (BOB-037 C): ``document`` posts the PNG
        UNCOMPRESSED (full resolution, the readable default), ``photo`` the inline-
        preview photo. No sink wired (the default) or an empty sink → a clean no-op.
        Best-effort: a flaky send is logged and swallowed so it can never break a turn
        whose text reply still lands.
        """
        if self._diagram_sink is None:
            return
        for diagram in self._diagram_sink.drain():
            try:
                await self._send_one_diagram(chat_id, diagram)
            except Exception:
                logger.exception("sending a diagram failed (ignored)")

    async def _send_one_diagram(self, chat_id: int, diagram: DiagramResult) -> None:
        """Send one drained diagram via the configured mode (document / photo)."""
        if self._diagram_send_as == "photo":
            await self._gateway.send_photo(
                chat_id=chat_id, photo=diagram.png, caption=diagram.caption
            )
            return
        await self._gateway.send_document(
            chat_id=chat_id, document=diagram.png, caption=diagram.caption
        )
