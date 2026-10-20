# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: no RUNTIME import cycle between Bob's modules (BOB-112).

beadloom's ``no-dependency-cycles`` reads every import since 2.2.0 — including the ones
under ``if TYPE_CHECKING:``, which exist only for annotations and never execute. On this
tree those type-only edges (30 of 98) close ONE strongly connected component of nine
modules, while the runtime edges alone close none. beadloom 9.0.0 can neither tell the two
apart nor exempt a cycle, so this test is the gate that judges what the rule cannot: the
imports Python actually executes. Module-level and function-level imports count; an import
under ``if TYPE_CHECKING:`` does not — at runtime it is a dead branch.

The nodes are the graph's: every top-level package under ``bob`` is one module, except
``application`` and ``infrastructure``, whose sub-packages are the nodes (``usecases``,
``router``, ``runtime``; ``telegram``, ``persistence``, ``llm``, …) — the same granularity
``.beadloom/_graph/services.yml`` declares, so a cycle this test names is a cycle the
graph would name once beadloom reads type-only imports as what they are.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import bob

if TYPE_CHECKING:
    from collections.abc import Iterable

_SRC_ROOT = Path(bob.__file__).parent
_SPLIT_PACKAGES = ("application", "infrastructure")


def _node_of(parts: tuple[str, ...]) -> str | None:
    """The graph node a dotted path under ``bob`` belongs to, or None for ``bob`` itself."""
    if not parts:
        return None
    if parts[0] in _SPLIT_PACKAGES:
        return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else parts[0]
    return parts[0]


def _runtime_imports(tree: ast.Module) -> list[str]:
    """Every ``bob.…`` module imported outside an ``if TYPE_CHECKING:`` block."""
    found: list[str] = []

    def walk(nodes: Iterable[ast.AST]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                walk(node.orelse)  # the dead branch is skipped, the live one is read
                continue
            if isinstance(node, ast.Import):
                found.extend(a.name for a in node.names if a.name.startswith("bob."))
            elif isinstance(node, ast.ImportFrom) and _is_first_party(node):
                found.append(node.module or "")
            walk(ast.iter_child_nodes(node))

    walk(tree.body)
    return found


def _is_first_party(node: ast.ImportFrom) -> bool:
    return node.level == 0 and node.module is not None and node.module.startswith("bob.")


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_edges() -> dict[str, set[str]]:
    edges: dict[str, set[str]] = defaultdict(set)
    for path in _SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(_SRC_ROOT).with_suffix("").parts
        src = _node_of(tuple(p for p in rel if p != "__init__"))
        if src is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _runtime_imports(tree):
            dst = _node_of(tuple(module.split(".")[1:]))
            if dst is not None and dst != src:
                edges[src].add(dst)
    return edges


def _cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan: every strongly connected component with more than one node, sorted."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []
    counter = 0

    def strongconnect(v: str) -> None:
        nonlocal counter
        index[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for v in sorted(edges):
        if v not in index:
            strongconnect(v)
    return sorted(components)


def test_runtime_imports_form_no_cycle_between_modules() -> None:
    edges = _runtime_edges()
    assert len(edges) >= 10, "the scan found almost nothing — the walk or the node map broke"
    assert _cycles(edges) == [], (
        "runtime import cycle(s) between modules (TYPE_CHECKING-only imports excluded): "
        f"{_cycles(edges)}"
    )


def test_type_checking_imports_are_not_runtime_edges() -> None:
    """The exclusion is real: a TYPE_CHECKING block contributes no edge, a function does."""
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from bob.memory.ports import X\n"
        "else:\n"
        "    from bob.social.ports import Y\n"
        "def f():\n"
        "    from bob.coding.ports import Z\n"
        "    return Z\n"
    )
    assert _runtime_imports(tree) == ["bob.social.ports", "bob.coding.ports"]
