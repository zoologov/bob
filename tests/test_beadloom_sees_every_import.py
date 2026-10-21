# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: beadloom INDEXES every import Bob's source makes (bob-7fo.7).

Every ``forbid_import`` rule in ``.beadloom/_graph/rules.yml`` judges the rows beadloom
writes to ``code_imports`` — and an import beadloom does not index is judged by no rule at
all. Measured on the pinned ``beadloom==9.0.0`` (review .5 Major-5, re-measured in bob-7fo.7
by sabotage in ``coding/naming.py`` against ``memory-boundary-no-coding-adapters``):

* ``import bob.memory.adapters.fts_recall`` — indexed, lint red;
* ``import bob.memory.adapters.fts_recall as _f`` — NO row, lint green;
* ``from ..memory.adapters import fts_recall`` — NO row, lint green;
* ``from bob import memory`` — row ``bob``, lint green;
* ``from bob.memory import adapters`` — row ``bob.memory`` (the package, not the
  sub-module it binds), lint green.

So each of those forms walks through every boundary rule. Bob's own cycle/order guard
(``tests/test_no_runtime_import_cycles.py``) reads them all, but it judges only cycles and
the vertical order — not the ~270 boundary rules. This test judges the TOOL, not the form of
the code (``CLAUDE.md`` §0.3 п.12): it rebuilds a fresh index with the beadloom on PATH in a
copy of ``src`` + ``.beadloom`` and requires that every first-party binding the ast reads is
a row there. A new blind form — today's or one a future beadloom grows — goes red here.

What it requires of a binding:

* one that crosses into another node — the FULL module it binds (``bob.memory.adapters``,
  not ``bob.memory``), because that is the path the boundary rules' globs judge;
* one inside its own node — the statement's own absolute module (an ``import`` name or a
  ``from`` base). 🔴 Named gap: ``from bob.coding import session_voice`` inside ``coding`` is
  indexed as ``bob.coding``, so an INTERNALS rule on ``bob/coding/<sub>*`` cannot see it.
  Two such statements exist today (``coding/usecases/coding_assistant.py``,
  ``interactive/usecases/session.py``, three bindings, ~45 call sites); closing the gap means
  rewriting them, which is the coordinator's decision, not this bead's.

Without beadloom on PATH the test SKIPs with the reason "NOT CHECKED" — never a silent
green. Locally PATH may hold an editable build whose ``--version`` reads like the release
(review .5 Major-3); in CI ``ci.yml`` installs the pinned release before pytest.
"""

from __future__ import annotations

import ast
import shutil
import sqlite3
import subprocess
from typing import TYPE_CHECKING, NamedTuple

import pytest

from tests.test_no_runtime_import_cycles import _SRC_ROOT, _node_of, _package_of, _resolve

if TYPE_CHECKING:
    from pathlib import Path

_REPO_ROOT = _SRC_ROOT.parents[1]
_REINDEX_TIMEOUT_S = 180
_MIN_BINDINGS = 1000  # measured 1329 on 2026-10-21; far fewer means the scan broke


class _Binding(NamedTuple):
    file: str  # relative to the repo root, as beadloom stores it
    line: int
    required: str  # the import path beadloom must have indexed at that line
    statement: str


def _file_node(path: Path) -> str | None:
    rel = path.relative_to(_SRC_ROOT).with_suffix("").parts
    return _node_of(tuple(p for p in rel if p != "__init__"))


def _statement_module(node: ast.Import | ast.ImportFrom, package: str, module: str) -> str:
    """The absolute module the statement itself names: the ``import`` name, the ``from`` base."""
    if isinstance(node, ast.Import):
        return module
    if node.level == 0:
        return node.module or ""
    anchor = package.split(".")
    anchor = anchor[: len(anchor) - (node.level - 1)]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def _required_rows(path: Path, source: str) -> list[_Binding]:
    """Every first-party binding in ``source`` and the row beadloom must hold for it."""
    file = str(path.relative_to(_REPO_ROOT))
    package = _package_of(path)
    src_node = _file_node(path)
    rows: list[_Binding] = []
    for node in ast.walk(ast.parse(source, filename=file)):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for module in _resolve(node, package):
            crosses = _node_of(tuple(module.split(".")[1:])) != src_node
            required = module if crosses else _statement_module(node, package, module)
            rows.append(_Binding(file, node.lineno, required, ast.unparse(node)))
    return rows


def _fresh_index(binary: str, root: Path) -> set[tuple[str, int, str]]:
    """Rebuild a clean index of a copy of ``src`` + ``.beadloom`` and read ``code_imports``."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.db-*")
    shutil.copytree(_REPO_ROOT / "src", root / "src", ignore=ignore)
    (root / ".beadloom").mkdir()
    shutil.copy2(_REPO_ROOT / ".beadloom" / "config.yml", root / ".beadloom" / "config.yml")
    shutil.copytree(_REPO_ROOT / ".beadloom" / "_graph", root / ".beadloom" / "_graph")
    run = subprocess.run(  # noqa: S603 — the binary is the beadloom found on PATH
        [binary, "reindex"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=_REINDEX_TIMEOUT_S,
        check=False,
    )
    assert run.returncode == 0, f"beadloom reindex failed ({run.returncode}): {run.stderr}"
    with sqlite3.connect(root / ".beadloom" / "beadloom.db") as db:
        found = db.execute("SELECT file_path, line_number, import_path FROM code_imports")
        return {(str(f), int(n), str(p)) for f, n, p in found}


def _blind(rows: list[_Binding], index: set[tuple[str, int, str]]) -> list[str]:
    return [
        f"{r.file}:{r.line} {r.statement!r} — beadloom has no {r.required!r} row"
        for r in rows
        if (r.file, r.line, r.required) not in index
    ]


def test_beadloom_indexes_every_import_bob_makes(tmp_path: Path) -> None:
    binary = shutil.which("beadloom")
    if binary is None:
        pytest.skip("beadloom is not on PATH — import parity with its index was NOT CHECKED")
    index = _fresh_index(binary, tmp_path)
    rows = [
        row
        for path in sorted(_SRC_ROOT.rglob("*.py"))
        for row in _required_rows(path, path.read_text(encoding="utf-8"))
    ]
    assert len(rows) >= _MIN_BINDINGS, (
        f"only {len(rows)} first-party bindings scanned — the ast walk broke; "
        "an empty scan proves nothing"
    )
    blind = _blind(rows, index)
    assert blind == [], (
        "import(s) beadloom does not index — no forbid_import rule judges them; write them "
        "as `from bob.x.y import name` or a plain `import bob.x.y` (no alias, not relative, "
        f"not `from bob import x`, not `from bob.x import <sub-module>` across nodes): {blind}"
    )


_COMMON = "src/bob/coding/naming.py"


@pytest.mark.parametrize(
    ("source", "required"),
    [
        ("import bob.memory.adapters.fts_recall as _f", ["bob.memory.adapters.fts_recall"]),
        ("from bob.memory import adapters", ["bob.memory.adapters"]),
        ("from bob import memory", ["bob.memory"]),
        ("from ..memory.adapters import fts_recall", ["bob.memory.adapters.fts_recall"]),
        ("from bob.memory.ports import X as Y", ["bob.memory.ports"]),
        ("from bob.coding import entities", ["bob.coding"]),
        ("from . import entities", ["bob.coding"]),
        ("import bob.coding.entities as e", ["bob.coding.entities"]),
        ("import os", []),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_required_row_per_binding(source: str, required: list[str]) -> None:
    """Crossing a node needs the full module; inside the node, the statement's own module."""
    path = _REPO_ROOT / _COMMON
    assert [r.required for r in _required_rows(path, source)] == required
    assert all(r.file == _COMMON and r.line == 1 for r in _required_rows(path, source))


def test_a_row_absent_from_the_index_is_reported_with_its_place() -> None:
    rows = _required_rows(_REPO_ROOT / _COMMON, "import bob.memory.ports as p")
    assert _blind(rows, set()) == [
        f"{_COMMON}:1 'import bob.memory.ports as p' — beadloom has no 'bob.memory.ports' row"
    ]
    assert _blind(rows, {(_COMMON, 1, "bob.memory.ports")}) == []
