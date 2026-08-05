# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure ``beadloom graph`` request core (BOB-091.1).

The planner is the security seam of the architecture-diagram capability: the model
names WHAT it wants (the whole map / one node / the internals of a container) and the
planner answers with ONE of three FIXED argv forms, every dynamic slot validated. No
flag is passed through, so a hostile "ref" cannot become ``--project`` or a write
command; a depth is a clamped integer, never a string the model chose.

Pure: request in, form out. This is the mutation target of the slice.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.graph_form import (
    MAX_GRAPH_DEPTH,
    diagram_carries_nodes,
    plan_graph_form,
    validate_graph_ref,
)

# --- the overview form: the whole map, no arguments at all ---------------------


def test_no_request_plans_the_overview_form() -> None:
    form = plan_graph_form()

    assert form.kind == "overview"
    assert form.args == ()
    assert form.fallback is None


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_ref_plans_the_overview_form(blank: str) -> None:
    # A model that sends an empty string means "no ref", not "a broken ref".
    assert plan_graph_form(blank).args == ()
    assert plan_graph_form(internals_of=blank).args == ()


# --- the node form: one node's neighbourhood, optionally with a depth ----------


def test_ref_plans_the_node_form() -> None:
    form = plan_graph_form("memory")

    assert form.kind == "node"
    assert form.args == ("memory",)
    assert form.fallback is None


def test_ref_with_depth_plans_the_bounded_node_form() -> None:
    form = plan_graph_form("memory", depth=2)

    assert form.args == ("memory", "--depth", "2")
    # The FORM KIND is what the capability reports back to the model ("это схема узла"),
    # so it must survive the depth branch too.
    assert form.kind == "node"
    assert form.fallback is None


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (0, "1"),
        (-7, "1"),
        (1, "1"),
        (MAX_GRAPH_DEPTH, str(MAX_GRAPH_DEPTH)),
        (99, str(MAX_GRAPH_DEPTH)),
    ],
)
def test_depth_is_clamped_into_the_bounded_window(asked: int, expected: str) -> None:
    # The depth slot is a clamped integer, so a traversal can never be unbounded
    # (nor zero/negative, which beadloom would read as "no graph at all").
    form = plan_graph_form("memory", depth=asked)

    assert form.args == ("memory", "--depth", expected)


def test_ref_is_lower_cased_before_it_reaches_argv() -> None:
    # Graph ref-ids are lower-case; normalising the case answers the question the
    # owner asked instead of refusing it, without widening the allowed shape.
    assert plan_graph_form("Memory").args == ("memory",)


# --- the components form: C4 internals of ONE container -----------------------


def test_internals_plans_the_c4_component_form() -> None:
    form = plan_graph_form(internals_of="bob-domain")

    assert form.kind == "components"
    assert form.args == (
        "--format",
        "c4",
        "--level",
        "component",
        "--scope",
        "bob-domain",
    )


def test_internals_falls_back_to_the_node_form_for_the_same_ref() -> None:
    # 🔴 Живой факт: ``--level component --scope <leaf>`` печатает ОДИН заголовок
    # ``C4Container`` — у листа графа внутренностей нет. The fallback keeps the answer
    # a real diagram (that node's links) instead of an empty picture.
    fallback = plan_graph_form(internals_of="memory").fallback

    assert fallback is not None
    assert fallback.kind == "node"
    assert fallback.args == ("memory",)
    assert fallback.fallback is None


def test_internals_wins_over_a_ref() -> None:
    # Asking for internals is the more specific request; the ref slot of the node form
    # is not silently used instead.
    form = plan_graph_form("memory", internals_of="bob-domain")

    assert form.kind == "components"
    assert form.args[-1] == "bob-domain"


# --- 🔴 the slot guard: no flag, no injection, no path can be smuggled ---------

_HOSTILE_REFS = [
    "--project=/etc",
    "-n",
    "--json",
    "memory; rm -rf /",
    "memory && whoami",
    "$(whoami)",
    "`id`",
    "../../etc/passwd",
    "/etc/passwd",
    "memory extra",
    "memory\nreindex",
    "a" * 65,
    "reindex --project /",
]


@pytest.mark.parametrize("hostile", _HOSTILE_REFS)
def test_hostile_ref_is_refused_not_forwarded(hostile: str) -> None:
    with pytest.raises(ValueError, match="graph ref"):
        plan_graph_form(hostile)


@pytest.mark.parametrize("hostile", _HOSTILE_REFS)
def test_hostile_internals_scope_is_refused(hostile: str) -> None:
    with pytest.raises(ValueError, match="graph ref"):
        plan_graph_form(internals_of=hostile)


@pytest.mark.parametrize("ref", ["memory", "bob-domain", "runtime-app", "bob-cjz.1", "llm"])
def test_real_graph_refs_are_accepted(ref: str) -> None:
    assert validate_graph_ref(ref) == ref


def test_validate_graph_ref_trims_and_lowers() -> None:
    assert validate_graph_ref("  Bob-Domain \n") == "bob-domain"


def test_ref_length_bound_is_inclusive_at_the_limit() -> None:
    # The bound is a length CAP, not an off-by-one refusal: a ref exactly at the limit is
    # a legal ref, one char over is not.
    at_limit = "a" * 64

    assert validate_graph_ref(at_limit) == at_limit
    with pytest.raises(ValueError, match="graph ref"):
        validate_graph_ref(at_limit + "a")


# --- the "did we actually get a diagram?" predicate ---------------------------


@pytest.mark.parametrize(
    "empty",
    [
        "",
        "   ",
        "graph LR",  # beadloom prints the header alone for an unresolved ref
        "graph LR\n",
        "C4Container",  # …and for a --scope with no internals
        "C4Container\n   \n\n",
    ],
)
def test_header_only_source_carries_no_nodes(empty: str) -> None:
    assert diagram_carries_nodes(empty) is False


def test_source_with_a_declaration_carries_nodes() -> None:
    source = 'graph LR\n    memory["memory<br/>(feature)"]\n'

    assert diagram_carries_nodes(source) is True
