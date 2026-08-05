# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure answer core of a drawing request — what the model is TOLD (BOB-091.6).

ONE responsibility: compose the model-facing answer to «нарисуй схему» — the mermaid
SOURCE Bob explains in his own words, which view was actually drawn, and what happened to
the PICTURE — plus the two honest refusals (nothing to draw / that was not a ref).

🔴 Why this core exists at all. The live smoke (BOB-091.6) showed Bob CALL
``draw_architecture``, receive 5 KB of real mermaid, retell it in words — and never send
an image, because "explain in words AND call ``render_diagram``" lived only in the tool
DESCRIPTION, i.e. in an agreement with the model. The picture is now attached by the
capability itself (a structural fix), and this core owns the other half — the WORDS about
that picture:

* ``sent`` — the image is already rendered and goes to the chat this very turn, so the
  model must not render it again (a second identical photo);
* ``unavailable`` — no renderer, a missing ``mmdc``, a timeout or broken mermaid: Bob says
  out loud that there will be no picture. Silence and a pretend send are both dishonest,
  and the source still comes back so a failed render never costs Bob his words.

Pure functions: no subprocess, no disk, no LLM. This is the mutation-tested core; the
render + queue-for-send lives behind :class:`~bob.capabilities.ports.DiagramRenderer` /
:class:`~bob.capabilities.ports.DiagramSink`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from bob.capabilities.introspection.graph_form import GraphFormKind

# What became of the picture for this drawing. Two values, because that is what the OWNER
# can tell apart: the image arrives, or it does not (whether the renderer was absent or
# failed is a machine detail he never sees).
type PictureStatus = Literal["sent", "unavailable"]

# Honest empty-result line: an unresolved ref yields a header-only diagram, i.e. a
# picture of nothing. Bob says so instead of rendering a blank image.
NOT_FOUND = (
    "Не нашёл такого узла в графе архитектуры — скажи об этом честно и предложи "
    "общую схему (вызов без аргументов)."
)

# Fed back when the DETAILED view had nothing to draw and the port degraded to the
# node's links, so the model never passes one view off as the other.
FALLBACK_NOTE = (
    "У этого узла в графе нет внутренностей (он не контейнер) — это схема его связей. "
    "Скажи об этом честно."
)

# Fed back when a slot was refused before any read (a flag / path / metacharacter, or a
# non-string value): the model gets the reason and can retry with a real ref-id.
REFUSED_REF = (
    "Так нельзя: 'ref'/'internals_of' — это id узла графа (например 'memory' или "
    "'bob-domain'), а не флаг или путь. Попроси схему заново с настоящим id."
)

# 🔴 The picture lines. ``sent`` also CLOSES the double-photo path: the model is told the
# image is handled, so it has no reason to call render_diagram on the same source (and if
# it does anyway, the shared per-turn sink already holds that source).
PICTURE_SENT = (
    "Картинка с этой схемой уже отрисована и уйдёт в чат этим же ходом — объясни "
    "своими словами, что на ней; render_diagram для этой схемы вызывать не нужно."
)
PICTURE_UNAVAILABLE = (
    "Картинку приложить не удалось (локальный рендерер недоступен) — объясни схему "
    "словами и честно скажи, что изображения не будет."
)

_PICTURE_LINES: dict[str, str] = {
    "sent": PICTURE_SENT,
    "unavailable": PICTURE_UNAVAILABLE,
}


def not_found_reply() -> dict[str, object]:
    """The honest answer when the graph drew nothing: no source, no picture, no guess."""
    return {"error": NOT_FOUND}


def refused_reply() -> dict[str, object]:
    """The honest answer when a ref slot was refused before any read."""
    return {"error": REFUSED_REF}


def drawn_reply(
    *,
    mermaid: str,
    drawn: GraphFormKind,
    requested: GraphFormKind,
    picture: PictureStatus,
) -> dict[str, object]:
    """Compose the answer for a diagram that WAS drawn: source, form, picture, note.

    ``mermaid`` always comes back — the picture is an ADDITION to Bob's words, never a
    replacement for them (that is what keeps a silent PNG impossible). ``drawn`` is the
    view the port actually produced and ``requested`` the one asked for: when they differ
    the answer carries :data:`FALLBACK_NOTE`, so Bob says "внутренностей там нет, вот
    связи" instead of passing one view off as the other. ``picture`` decides which of the
    two picture lines is fed back — the announcement or the honest "картинки не будет".
    """
    reply: dict[str, object] = {
        "mermaid": mermaid,
        "form": drawn,
        "picture": _PICTURE_LINES[picture],
    }
    if drawn != requested:
        reply["note"] = FALLBACK_NOTE
    return reply
