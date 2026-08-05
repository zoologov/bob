# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``draw_architecture`` — Bob draws his own architecture (BOB-091.1/.6).

The capability hands the model the mermaid SOURCE of the architecture graph AND queues
the rendered picture itself: the owner gets both an explanation in words and the image,
and a silent PNG stays impossible (the model always writes the text).

🔴 BOB-091.6 — what the live smoke taught: до фикса связка «объясни словами И вызови
render_diagram» жила ТОЛЬКО в описании инструмента, и тесты доказывали ровно это — что в
ОПИСАНИИ есть слово ``render_diagram``. Модель получила 5 КБ mermaid, пересказала его
словами и картинку не прислала. Поэтому связка теперь проверяется ЧЕРЕЗ ГРАНИЦУ: вызвали
капабилити — в синке лежит картинка, а модели ушёл mermaid. Ассерт про текст описания
поведения не доказывает.

Deterministic on the fake port + fake renderer — no subprocess, no disk. The real
``mmdc`` on the real ``beadloom graph`` output is covered in
``tests/infrastructure/diagrams/test_real_architecture_render.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from bob.capabilities.adapters.diagrams.mmdc_renderer import DiagramRenderError
from bob.capabilities.usecases.diagram_attachment import DiagramAttachment
from bob.capabilities.usecases.draw_architecture import (
    make_draw_architecture_capability,
)
from bob.capabilities.usecases.render_diagram import (
    CollectingDiagramSink,
    make_render_diagram_capability,
)

from .fakes import FAKE_PNG, FakeDiagramRenderer, FakeRepoIntrospector

if TYPE_CHECKING:
    from bob.capabilities.ports import Capability

_MERMAID = 'graph LR\n    memory["memory<br/>(feature)"]\n    memory --> bob'


def test_capability_advertises_the_draw_architecture_contract() -> None:
    cap = make_draw_architecture_capability(FakeRepoIntrospector())

    assert cap.name == "draw_architecture"
    assert cap.permission == "safe"
    schema = cap.input_schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["ref"] == {"type": "string"}
    assert properties["internals_of"] == {"type": "string"}
    assert properties["depth"] == {"type": "integer"}
    # Nothing is required: the no-argument call is the whole-system overview.
    assert "required" not in schema


def test_description_advertises_the_source_and_the_handled_picture() -> None:
    # 🔴 This is the WEAK test of the pair, kept only because the advertised contract is
    # itself observable: it says nothing about whether a picture actually appears. The
    # connection is asserted through the boundary below
    # (test_the_picture_is_queued_and_the_source_still_reaches_the_model).
    description = make_draw_architecture_capability(FakeRepoIntrospector()).description

    assert "mermaid" in description.lower()
    assert "picture" in description.lower()


async def test_no_arguments_asks_the_port_for_the_overview() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({})

    assert introspector.diagram_calls == [(None, None, None)]
    assert isinstance(result, Mapping)
    assert result["mermaid"] == _MERMAID
    assert result["form"] == "overview"


async def test_ref_and_depth_reach_the_port() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="node")
    cap = make_draw_architecture_capability(introspector)

    await cap.execute({"ref": "memory", "depth": 2})

    assert introspector.diagram_calls == [("memory", 2, None)]


async def test_depth_written_as_a_string_is_still_understood() -> None:
    # Models routinely send "2" for an integer field; dropping it silently would answer
    # a different question than the one asked.
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="node")
    cap = make_draw_architecture_capability(introspector)

    await cap.execute({"ref": "memory", "depth": "2"})

    assert introspector.diagram_calls == [("memory", 2, None)]


async def test_nonsense_depth_is_ignored_rather_than_guessed() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="node")
    cap = make_draw_architecture_capability(introspector)

    await cap.execute({"ref": "memory", "depth": "поглубже"})

    assert introspector.diagram_calls == [("memory", None, None)]


async def test_internals_of_reaches_the_port() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="components")
    cap = make_draw_architecture_capability(introspector)

    await cap.execute({"internals_of": "bob-domain"})

    assert introspector.diagram_calls == [(None, None, "bob-domain")]


async def test_a_fallback_view_is_reported_honestly() -> None:
    # The port asked for components and drew the node form (a leaf has no internals);
    # the model must be told, so Bob says "внутренностей нет, вот связи".
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="node")
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"internals_of": "memory"})

    assert isinstance(result, Mapping)
    assert result["form"] == "node"
    note = str(result["note"])
    assert "внутренност" in note.lower()


async def test_a_matching_view_carries_no_correction_note() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID, diagram_form="components")
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"internals_of": "bob-domain"})

    assert isinstance(result, Mapping)
    assert "note" not in result


async def test_empty_graph_is_honest_not_found_without_mermaid() -> None:
    # ``beadloom graph nosuchnode`` exits 0 with a bare header: an empty picture. Bob
    # must say so, not render nothing and claim a diagram.
    introspector = FakeRepoIntrospector(diagram="graph LR", diagram_form="node")
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"ref": "nosuchnode"})

    assert isinstance(result, Mapping)
    assert "mermaid" not in result
    assert "не нашёл" in str(result["error"]).lower()


async def test_refused_ref_becomes_a_readable_error_not_a_crashed_turn() -> None:
    introspector = FakeRepoIntrospector(raise_on_diagram=True)
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"ref": "--project=/etc"})

    assert isinstance(result, Mapping)
    assert "mermaid" not in result
    assert "ref" in str(result["error"]).lower()


async def test_non_string_ref_is_refused_readably() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"ref": 42})

    assert isinstance(result, Mapping)
    assert "error" in result
    assert introspector.diagram_calls == []


async def test_non_string_internals_of_is_refused_readably_too() -> None:
    # 🔴 Found by mutation (BOB-091.6): the guard names BOTH ref slots, but only ``ref``
    # was covered — so mutating the ``internals_of`` key survived. A number in that slot
    # must be refused, not silently read as "no ref" (Bob would answer the overview to a
    # question about internals).
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({"internals_of": 42})

    assert isinstance(result, Mapping)
    assert "error" in result
    assert "mermaid" not in result
    assert introspector.diagram_calls == []


# --- BOB-091.6: the picture is attached STRUCTURALLY, not by agreement ---------


def _drawing_over(
    introspector: FakeRepoIntrospector, renderer: FakeDiagramRenderer
) -> tuple[Capability, CollectingDiagramSink]:
    """Build the capability over a real sink + the given fake renderer.

    The sink is the SAME kind of per-turn collector the reply path drains to post the
    photo, so "a picture appeared in the sink" IS the observable "the owner gets an
    image" — no private state, no internals.
    """
    sink = CollectingDiagramSink()
    cap = make_draw_architecture_capability(
        introspector, attachment=DiagramAttachment(renderer, sink)
    )
    return cap, sink


async def test_the_picture_is_queued_and_the_source_still_reaches_the_model() -> None:
    # 🔴 THE test the live smoke needed: one call, and BOTH halves are there — the
    # rendered image waits in the per-turn sink AND the mermaid source went back to the
    # model so Bob explains it in words. Neither is traded for the other.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer()
    cap, sink = _drawing_over(introspector, renderer)

    result = await cap.execute({})

    queued = sink.drain()
    assert len(queued) == 1, "картинка не встала в синк — owner её не получит"
    assert queued[0].png == FAKE_PNG
    assert queued[0].caption
    assert isinstance(result, Mapping)
    assert result["mermaid"] == _MERMAID, "модель осталась без источника для слов"


async def test_the_renderer_is_handed_exactly_the_graph_source() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer()
    cap, _sink = _drawing_over(introspector, renderer)

    await cap.execute({})

    # Exactly ONE render of exactly the graph's own source: no retry (so the turn waits
    # at most the single configured ``diagrams.timeout``), no re-derived diagram.
    assert renderer.sources == [_MERMAID]


async def test_the_queued_picture_carries_its_source_so_an_echo_is_deduped() -> None:
    # BOB-037 A dedups an inline ```mermaid fence in Bob's reply against what the tools
    # queued — by SOURCE. Without it the same diagram would be sent twice.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    cap, sink = _drawing_over(introspector, FakeDiagramRenderer())

    await cap.execute({})

    assert [entry.source for entry in sink.pending()] == [_MERMAID]


async def test_a_failed_render_is_admitted_honestly_and_never_crashes_the_turn() -> None:
    # 🔴 mmdc missing / timeout / broken mermaid: Bob still answers in words and says
    # out loud that there will be no picture — never silence, never a pretend send.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer(raises=DiagramRenderError("mmdc not installed"))
    cap, sink = _drawing_over(introspector, renderer)

    result = await cap.execute({})

    assert sink.drain() == (), "картинки нет — в синке ничего лежать не должно"
    assert isinstance(result, Mapping)
    assert result["mermaid"] == _MERMAID
    picture = str(result["picture"]).lower()
    assert "не" in picture
    assert "уже" not in picture, "нельзя делать вид, что картинка ушла"


async def test_a_render_timeout_reaches_the_model_as_the_honest_no_picture_line() -> None:
    # The adapter turns its own ``diagrams.timeout`` into a DiagramRenderError; the
    # capability must treat it like any other failure (honest line, no exception).
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer(raises=DiagramRenderError("mmdc render timed out"))
    cap, sink = _drawing_over(introspector, renderer)

    result = await cap.execute({})

    assert sink.drain() == ()
    assert isinstance(result, Mapping)
    assert "picture" in result


async def test_nothing_is_rendered_when_the_graph_drew_nothing() -> None:
    # An unresolved ref yields a header-only diagram: rendering it would post a blank
    # image AND burn a subprocess for nothing.
    introspector = FakeRepoIntrospector(diagram="graph LR", diagram_form="node")
    renderer = FakeDiagramRenderer()
    cap, sink = _drawing_over(introspector, renderer)

    result = await cap.execute({"ref": "nosuchnode"})

    assert renderer.sources == []
    assert sink.drain() == ()
    assert isinstance(result, Mapping)
    assert "picture" not in result


async def test_nothing_is_rendered_when_the_ref_was_refused() -> None:
    # The port refuses a flag-shaped ref BEFORE any read (as the real argv guard does),
    # so there is no source — and nothing to render.
    introspector = FakeRepoIntrospector(raise_on_diagram=True)
    renderer = FakeDiagramRenderer()
    cap, sink = _drawing_over(introspector, renderer)

    await cap.execute({"ref": "--project=/etc"})

    assert renderer.sources == []
    assert sink.drain() == ()


async def test_nothing_is_rendered_when_the_ref_was_not_even_a_string() -> None:
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer()
    cap, sink = _drawing_over(introspector, renderer)

    await cap.execute({"ref": 42})

    assert introspector.diagram_calls == []
    assert renderer.sources == []
    assert sink.drain() == ()


async def test_the_same_diagram_is_not_rendered_twice_in_one_turn() -> None:
    # Two draws of the same view in one turn cost ONE render and post ONE photo.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer()
    cap, sink = _drawing_over(introspector, renderer)

    first = await cap.execute({})
    second = await cap.execute({})

    assert renderer.sources == [_MERMAID]
    assert len(sink.drain()) == 1
    assert isinstance(first, Mapping)
    assert isinstance(second, Mapping)
    # The second call still reports the picture as handled — it IS queued.
    assert second["picture"] == first["picture"]


async def test_a_model_that_calls_render_diagram_anyway_adds_no_second_photo() -> None:
    # 🔴 The model is TOLD not to re-render, but a told-so is an agreement. Structurally:
    # the shared sink already holds this source, so the second call is a no-op send-wise.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    renderer = FakeDiagramRenderer()
    sink = CollectingDiagramSink()
    drawing = make_draw_architecture_capability(
        introspector, attachment=DiagramAttachment(renderer, sink)
    )
    rendering = make_render_diagram_capability(renderer, sink)

    await drawing.execute({})
    await rendering.execute({"mermaid": _MERMAID})

    assert len(sink.drain()) == 1, "owner получил бы две одинаковые картинки"
    assert renderer.sources == [_MERMAID]


async def test_without_a_wired_renderer_bob_says_there_will_be_no_picture() -> None:
    # ``diagrams.enabled`` off → no renderer at all. The answer stays honest instead of
    # promising an image nobody will send.
    introspector = FakeRepoIntrospector(diagram=_MERMAID)
    cap = make_draw_architecture_capability(introspector)

    result = await cap.execute({})

    assert isinstance(result, Mapping)
    assert result["mermaid"] == _MERMAID
    assert "не" in str(result["picture"]).lower()
