# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``draw_architecture`` — Bob draws his own architecture (BOB-091.1).

The capability hands the model the mermaid SOURCE of the architecture graph, not a
picture: the owner's decision is that Bob explains what the diagram shows AND attaches
the image via the existing ``render_diagram`` — never a silent PNG. So the contract
asserted here is: the source reaches the model, the form actually drawn is reported
(honesty when a detailed view had nothing to show), an empty graph answers honestly, and
a refused ref comes back as a readable error instead of a crashed turn.

Deterministic on the fake port — no subprocess, no disk.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.capabilities.usecases.draw_architecture import (
    make_draw_architecture_capability,
)

from .fakes import FakeRepoIntrospector

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


def test_description_tells_the_model_to_render_and_explain() -> None:
    # 🔴 The owner's decision lives in the description: source + words + render_diagram.
    description = make_draw_architecture_capability(FakeRepoIntrospector()).description

    assert "render_diagram" in description
    assert "mermaid" in description.lower()


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
