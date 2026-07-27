# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``render_diagram`` — mermaid → local PNG → photo result (BOB-035 .1).

A thin wrapper over the :class:`~bob.domain.ports.DiagramRenderer` port: it renders
the user/Bob-provided mermaid source LOCALLY, pushes the resulting
:class:`~bob.domain.ports.DiagramResult` (PNG + caption) into a per-turn
:class:`~bob.domain.ports.DiagramSink`, and returns a short text confirmation for the
tool-loop (the photo itself is sent by the reply path, which holds the chat_id). It
renders only its INPUT — it reads no personal data. The renderer is faked here (no
real ``mmdc``); the graceful path is driven by a renderer that raises
:class:`DiagramRenderError`.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.capabilities.adapters.diagrams.mmdc_renderer import DiagramRenderError
from bob.capabilities.usecases.render_diagram import (
    CollectingDiagramSink,
    make_render_diagram_capability,
)
from bob.domain.ports import DiagramResult

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


class _FakeRenderer:
    """A scripted :class:`DiagramRenderer`: records source, returns canned PNG."""

    def __init__(self, *, png: bytes = _PNG, raises: BaseException | None = None) -> None:
        self.sources: list[str] = []
        self._png = png
        self._raises = raises

    async def render(self, mermaid_source: str) -> bytes:
        self.sources.append(mermaid_source)
        if self._raises is not None:
            raise self._raises
        return self._png


def test_capability_advertises_the_render_diagram_contract() -> None:
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    assert cap.name == "render_diagram"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["mermaid"] == {"type": "string"}
    assert schema["required"] == ["mermaid"]


def test_description_notes_it_renders_only_its_input_no_personal_data() -> None:
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    low = cap.description.lower()
    assert "mermaid" in low
    # It renders only its INPUT — the description must say it reads no personal data.
    assert "personal" in low or "private" in low


async def test_execute_renders_and_pushes_a_photo_result_into_the_sink() -> None:
    renderer = _FakeRenderer()
    sink = CollectingDiagramSink()
    cap = make_render_diagram_capability(renderer, sink)

    await cap.execute({"mermaid": "graph TD; A-->B"})

    assert renderer.sources == ["graph TD; A-->B"]
    pending = sink.drain()
    assert len(pending) == 1
    assert isinstance(pending[0], DiagramResult)
    assert pending[0].png == _PNG
    assert pending[0].caption


async def test_execute_returns_a_text_confirmation_for_the_tool_loop() -> None:
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    result = await cap.execute({"mermaid": "graph TD; A-->B"})

    assert isinstance(result, Mapping)
    # The tool-loop only ever sees text; the confirmation signals the photo was sent.
    assert isinstance(result["status"], str)
    assert result["status"]


async def test_execute_degrades_gracefully_when_the_renderer_raises() -> None:
    sink = CollectingDiagramSink()
    cap = make_render_diagram_capability(
        _FakeRenderer(raises=DiagramRenderError("mmdc not installed")), sink
    )

    result = await cap.execute({"mermaid": "graph TD; A-->B"})

    # No crash, no photo pushed — an honest "renderer unavailable" text instead.
    assert sink.drain() == ()
    assert isinstance(result, Mapping)
    assert "error" in result
    assert "render" in str(result["error"]).lower()


async def test_execute_requires_a_string_mermaid_argument() -> None:
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    with pytest.raises(ValueError, match="mermaid"):
        await cap.execute({"mermaid": None})


async def test_execute_with_missing_mermaid_key_raises() -> None:
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    with pytest.raises(ValueError, match="mermaid"):
        await cap.execute({})


def test_collecting_sink_drains_and_clears() -> None:
    sink = CollectingDiagramSink()
    sink.push(DiagramResult(png=_PNG, caption="one"))
    sink.push(DiagramResult(png=_PNG, caption="two"))

    drained = sink.drain()

    assert [r.caption for r in drained] == ["one", "two"]
    # A second drain is empty — each turn starts fresh (no leak across turns).
    assert sink.drain() == ()


def test_collecting_sink_pending_peeks_without_clearing() -> None:
    # BOB-037: the inline auto-render peeks the sink (to dedup) without draining it.
    sink = CollectingDiagramSink()
    sink.push(DiagramResult(png=_PNG, caption="one", source="graph TD; A-->B"))

    peeked = sink.pending()

    assert [r.source for r in peeked] == ["graph TD; A-->B"]
    # The peek did NOT clear — drain still returns the entry.
    assert len(sink.drain()) == 1


async def test_execute_records_the_mermaid_source_on_the_result() -> None:
    # BOB-037: the tool-rendered result carries its mermaid source so the inline
    # auto-render can dedup against it.
    sink = CollectingDiagramSink()
    cap = make_render_diagram_capability(_FakeRenderer(), sink)

    await cap.execute({"mermaid": "graph TD; A-->B"})

    assert [r.source for r in sink.pending()] == ["graph TD; A-->B"]


# --- BOB-035 .2: privacy / per-turn isolation guardrails -----------------------


async def test_execute_renders_only_its_input_no_personal_data_read() -> None:
    # PRIVACY GUARDRAIL: the capability hands the renderer EXACTLY the mermaid it was
    # given and nothing else — it never reaches for memory / soul / config / files.
    renderer = _FakeRenderer()
    cap = make_render_diagram_capability(renderer, CollectingDiagramSink())

    await cap.execute({"mermaid": "graph TD; secret-free"})

    # The renderer saw only the single mermaid source — no extra data was fetched/passed.
    assert renderer.sources == ["graph TD; secret-free"]


async def test_execute_ignores_extra_args_renders_only_mermaid() -> None:
    # Even if the model passes spurious extra arguments, only ``mermaid`` is rendered —
    # the capability does not interpret a path/personal field hidden in the args.
    renderer = _FakeRenderer()
    cap = make_render_diagram_capability(renderer, CollectingDiagramSink())

    await cap.execute(
        {"mermaid": "graph TD; A-->B", "file": "/etc/passwd", "user_id": 42}
    )

    assert renderer.sources == ["graph TD; A-->B"]


def test_capability_permission_is_safe() -> None:
    # GUARDRAIL: render_diagram is conversation-safe — local, reads nothing private.
    cap = make_render_diagram_capability(_FakeRenderer(), CollectingDiagramSink())

    assert cap.permission == "safe"


async def test_each_turn_uses_a_fresh_drain_no_cross_turn_bleed() -> None:
    # PER-TURN ISOLATION: two renders followed by a drain yield both; a render in a
    # "next turn" yields ONLY that one — the prior turn's results never leak through.
    sink = CollectingDiagramSink()
    cap = make_render_diagram_capability(_FakeRenderer(), sink)

    await cap.execute({"mermaid": "turn1-a"})
    await cap.execute({"mermaid": "turn1-b"})
    assert len(sink.drain()) == 2  # turn 1 drained

    await cap.execute({"mermaid": "turn2"})
    drained = sink.drain()
    assert len(drained) == 1  # turn 2 holds only its own diagram, no bleed
