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
under ``if TYPE_CHECKING:`` does not — at runtime it is a dead branch. Every import FORM is
read (bob-etb.8): ``import bob.x``, ``from bob.x import y``, ``from bob import x``, ``from
bob.application import usecases`` and relative imports all resolve to the module they bind.

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

import pytest

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


def _package_of(path: Path) -> str:
    """The ``__package__`` of a source file under ``bob`` — what its relative imports resolve
    against: the file's directory, for a plain module and for an ``__init__.py`` alike."""
    return ".".join(("bob", *path.relative_to(_SRC_ROOT).parts[:-1]))


def _is_first_party(dotted: str) -> bool:
    return dotted == "bob" or dotted.startswith("bob.")


def _is_source_module(dotted: str) -> bool:
    """True if ``dotted`` is a module or a package on disk (``x.py`` or ``x/__init__.py``)."""
    base = _SRC_ROOT.parent.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _resolve_from(node: ast.ImportFrom, package: str) -> list[str]:
    """The ``bob`` modules a ``from … import …`` binds, in every form (bob-etb.8, review M2).

    Absolute or relative (``level > 0`` resolves against ``package``, as Python does); each
    imported name that is itself a sub-module/sub-package resolves to it — so ``from bob
    import social`` is ``bob.social`` and ``from bob.application import usecases`` is
    ``bob.application.usecases`` — while a symbol resolves to the module it comes from.
    """
    if node.level == 0:
        base = node.module or ""
    else:
        anchor = package.split(".")
        if node.level - 1 >= len(anchor):
            raise ValueError(
                f"relative import of level {node.level} goes beyond the top package of {package}"
            )
        anchor = anchor[: len(anchor) - (node.level - 1)]
        base = ".".join([*anchor, *([node.module] if node.module else [])])
    if not _is_first_party(base):
        return []
    resolved = (
        f"{base}.{a.name}" if a.name != "*" and _is_source_module(f"{base}.{a.name}") else base
        for a in node.names
    )
    return list(dict.fromkeys(resolved))  # one entry per bound module per statement


def _resolve(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    """The ``bob`` modules one import statement binds (non-first-party names are dropped)."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names if _is_first_party(a.name)]
    return _resolve_from(node, package)


def _runtime_imports(tree: ast.Module, package: str) -> list[str]:
    """Every ``bob`` module imported outside an ``if TYPE_CHECKING:`` block, in any form."""
    found: list[str] = []

    def walk(nodes: Iterable[ast.AST]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                walk(node.orelse)  # the dead branch is skipped, the live one is read
                continue
            if isinstance(node, ast.Import | ast.ImportFrom):
                found.extend(_resolve(node, package))
            walk(ast.iter_child_nodes(node))

    walk(tree.body)
    return found


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
        for module in _runtime_imports(tree, _package_of(path)):
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
        "    from bob import memory\n"
        "    from ..memory import ports\n"
        "else:\n"
        "    from bob.social.ports import Y\n"
        "    from . import mood\n"
        "def f():\n"
        "    from bob.coding.ports import Z\n"
        "    from bob import presence\n"
        "    return Z\n"
    )
    assert _runtime_imports(tree, "bob.personality") == [
        "bob.social.ports",
        "bob.personality.mood",
        "bob.coding.ports",
        "bob.presence",
    ]


# --- BOB-113: no TYPE_CHECKING-only import points UPWARD ------------------------------------
#
# The order of the verticals, top (depends on the rest) to bottom (depended upon). DERIVED
# from the runtime edges (module- and function-level imports), measured 2026-10-21 after
# BOB-113 W3: every runtime edge between two of these nodes points from an earlier entry to
# a later one (``test_runtime_edges_follow_the_declared_vertical_order`` holds that). The
# class of defect BOB-113 removed was a type-only import pointing the OTHER way — dead at
# runtime, yet it closed the nine-module cycle beadloom reports. ``kernel`` sits below
# everything (anyone may reference it, it references no one); nodes absent from the list
# (``coding``, ``interactive``, ``identity``, ``presence``, ``infrastructure.llm``,
# ``infrastructure.persistence``, …) are outside this guard and are skipped, not failed.
# Graph ref_ids: ``usecases`` = application.usecases, ``telegram`` = infrastructure.telegram,
# ``runtime-app`` = application.runtime.
_VERTICAL_ORDER: tuple[str, ...] = (
    "application.usecases",
    "capabilities",
    "social",
    "infrastructure.telegram",
    "proactivity",
    "memory",
    "application.runtime",
    "conversation",
    "personality",
)
_KERNEL = "kernel"


def _type_checking_imports(tree: ast.Module, package: str) -> list[tuple[str, int]]:
    """Every ``bob`` module imported INSIDE an ``if TYPE_CHECKING:`` block, with its line."""
    found: list[tuple[str, int]] = []

    def collect(nodes: Iterable[ast.AST]) -> None:
        for node in nodes:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import | ast.ImportFrom):
                    found.extend((module, sub.lineno) for module in _resolve(sub, package))

    def walk(nodes: Iterable[ast.AST]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                collect(node.body)  # the type-only branch is what this guard reads
                walk(node.orelse)  # the live branch may nest another TYPE_CHECKING block
                continue
            walk(ast.iter_child_nodes(node))

    walk(tree.body)
    return found


def _type_only_edges() -> list[tuple[str, str, str]]:
    """(src node, dst node, ``file:line``) for every cross-node TYPE_CHECKING-only import."""
    edges: list[tuple[str, str, str]] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(_SRC_ROOT).with_suffix("").parts
        src = _node_of(tuple(p for p in rel if p != "__init__"))
        if src is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module, line in _type_checking_imports(tree, _package_of(path)):
            dst = _node_of(tuple(module.split(".")[1:]))
            if dst is not None and dst != src:
                where = f"{path.relative_to(_SRC_ROOT.parent)}:{line}"
                edges.append((src, dst, where))
    return edges


def _points_upward(src: str, dst: str) -> bool | None:
    """True if ``src → dst`` goes up the declared order, False if down, None if out of scope."""
    if src == _KERNEL:
        return True  # the kernel is below every module: any edge out of it goes up
    if dst == _KERNEL:
        return False
    if src not in _VERTICAL_ORDER or dst not in _VERTICAL_ORDER:
        return None
    return _VERTICAL_ORDER.index(dst) <= _VERTICAL_ORDER.index(src)


def test_no_type_checking_import_points_upward_against_the_vertical_order() -> None:
    edges = _type_only_edges()
    in_scope = [e for e in edges if _points_upward(e[0], e[1]) is not None]
    assert len(in_scope) >= 5, (
        f"only {len(in_scope)} type-only imports between ordered modules were scanned — "
        "the TYPE_CHECKING collector or the node map broke; an empty scan proves nothing"
    )
    upward = [f"{s} → {d} ({where})" for s, d, where in in_scope if _points_upward(s, d)]
    assert upward == [], (
        "TYPE_CHECKING-only import(s) point UPWARD against the vertical order "
        f"{' → '.join(_VERTICAL_ORDER)} (kernel below all): {upward}"
    )


def test_runtime_edges_follow_the_declared_vertical_order() -> None:
    """The order constant is honest: no RUNTIME edge between ordered modules goes up either.

    If this fails, the runtime graph moved and ``_VERTICAL_ORDER`` must be re-derived — the
    message names the edge that broke it.
    """
    edges = _runtime_edges()
    upward = sorted(
        f"{src} → {dst}" for src, dsts in edges.items() for dst in dsts if _points_upward(src, dst)
    )
    assert upward == [], f"runtime edge(s) contradict _VERTICAL_ORDER, re-derive it: {upward}"


def test_type_checking_collector_reads_only_the_type_only_branch() -> None:
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "import typing\n"
        "if TYPE_CHECKING:\n"
        "    from bob.memory.ports import X\n"
        "    import bob.social.roster\n"
        "    from bob import social\n"
        "    from ..application import usecases\n"
        "else:\n"
        "    from bob.coding.ports import Y\n"
        "    from bob import memory\n"
        "from bob.kernel.events import Z\n"
        "from . import mood\n"
        "def f():\n"
        "    if typing.TYPE_CHECKING:\n"
        "        from bob.personality.voice import V\n"
        "        from .voice import W\n"
    )
    assert _type_checking_imports(tree, "bob.personality") == [
        ("bob.memory.ports", 4),
        ("bob.social.roster", 5),
        ("bob.social", 6),
        ("bob.application.usecases", 7),
        ("bob.personality.voice", 15),
        ("bob.personality.voice", 16),
    ]


def test_vertical_order_direction_and_scope() -> None:
    assert _points_upward("personality", "social") is True
    assert _points_upward("social", "personality") is False
    assert _points_upward("kernel", "personality") is True
    assert _points_upward("kernel", "coding") is True
    assert _points_upward("personality", "kernel") is False
    assert _points_upward("coding", "memory") is None
    assert _points_upward("memory", "infrastructure.llm") is None


# --- bob-etb.8 (review M2): the collectors read EVERY import form -------------------------
#
# A guard that reads only ``from bob.x.y import …`` inherits the illusion of that form
# (§0.3 п.12): ``from bob import social`` under TYPE_CHECKING passed both this guard and
# beadloom 9.0.0. Each form below must resolve to the dotted module it actually binds; a
# name that is a sub-module/sub-package resolves to it, a symbol resolves to its package.
# The file under test sits in package ``bob.personality`` (as ``bob/personality/voice.py``).
_PERSONALITY = "bob.personality"

_IMPORT_FORMS: tuple[tuple[str, list[str]], ...] = (
    ("import bob.social.roster", ["bob.social.roster"]),
    ("import bob.social.roster as r, os", ["bob.social.roster"]),
    ("from bob.social.roster import build_roster", ["bob.social.roster"]),
    ("from bob import social", ["bob.social"]),
    ("from bob import social as s, memory", ["bob.social", "bob.memory"]),
    ("from bob.social import roster", ["bob.social.roster"]),
    ("from bob.social import AllowlistStore", ["bob.social"]),
    ("from bob.application import usecases", ["bob.application.usecases"]),
    ("from bob.infrastructure import telegram", ["bob.infrastructure.telegram"]),
    ("from bob.application import reliability", ["bob.application.reliability"]),
    ("from bob.application import NOT_A_MODULE", ["bob.application"]),
    ("from . import mood", ["bob.personality.mood"]),
    ("from .voice import improvement_directive", ["bob.personality.voice"]),
    ("from .. import social", ["bob.social"]),
    ("from ..social import roster", ["bob.social.roster"]),
    ("from ..social.roster import build_roster", ["bob.social.roster"]),
    ("from ..application import usecases", ["bob.application.usecases"]),
    ("import os", []),
    ("from typing import TYPE_CHECKING", []),
    ("import bobcat", []),
    ("from bobcat import bob", []),
)


@pytest.mark.parametrize(("source", "expected"), _IMPORT_FORMS, ids=[f[0] for f in _IMPORT_FORMS])
def test_runtime_collector_resolves_every_import_form(source: str, expected: list[str]) -> None:
    assert _runtime_imports(ast.parse(source), _PERSONALITY) == expected


@pytest.mark.parametrize(("source", "expected"), _IMPORT_FORMS, ids=[f[0] for f in _IMPORT_FORMS])
def test_type_checking_collector_resolves_every_import_form(
    source: str, expected: list[str]
) -> None:
    tree = ast.parse("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    " + source)
    assert _type_checking_imports(tree, _PERSONALITY) == [(m, 3) for m in expected]


def test_relative_import_resolves_against_the_package_of_an_init_module() -> None:
    """In ``bob/social/__init__.py`` the package is ``bob.social`` itself, not ``bob``."""
    assert _runtime_imports(ast.parse("from .roster import x"), "bob.social") == [
        "bob.social.roster"
    ]
    assert _runtime_imports(ast.parse("from . import social"), "bob") == ["bob.social"]


def test_relative_import_beyond_the_top_package_fails_loudly() -> None:
    """Python rejects it at import time; the guard must not silently drop it either."""
    with pytest.raises(ValueError, match="beyond"):
        _runtime_imports(ast.parse("from ... import social"), _PERSONALITY)


@pytest.mark.parametrize(
    ("relative", "package"),
    [
        (("personality", "voice.py"), "bob.personality"),
        (("personality", "__init__.py"), "bob.personality"),
        (("application", "usecases", "handle_message.py"), "bob.application.usecases"),
        (("app.py",), "bob"),
        (("__init__.py",), "bob"),
    ],
)
def test_package_of_a_source_file(relative: tuple[str, ...], package: str) -> None:
    assert _package_of(_SRC_ROOT.joinpath(*relative)) == package


def test_from_bob_import_subpackage_under_type_checking_is_judged_as_an_upward_edge() -> None:
    """The review's deception (M2): the form resolves to a node the order judges."""
    tree = ast.parse(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from bob import social\n"
    )
    [(module, _line)] = _type_checking_imports(tree, _PERSONALITY)
    dst = _node_of(tuple(module.split(".")[1:]))
    assert dst == "social"
    assert _points_upward("personality", dst) is True
