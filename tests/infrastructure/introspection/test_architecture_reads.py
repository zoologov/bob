# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The read-only ``beadloom graph`` / ``why`` seam of the introspector (BOB-091.1).

``graph`` and ``why`` sat in the adapter's allowlist since BOB-017 as DEAD entries — no
port method ever reached them, so Bob could neither draw his architecture nor say what
breaks if you touch ``memory``. This module drives the two new port methods through the
recording-fake subprocess boundary (nothing spawns) and asserts:

* the EXACT argv of each of the three allowed ``graph`` forms;
* the honest fallback: a ``--scope`` with no internals (the live ``C4Container``-only
  output) re-asks the node form and REPORTS which form was actually drawn;
* the ``why`` output comes back digested (no Rich frames);
* 🔴 the read-only invariant is not weakened: every WRITE beadloom subcommand
  (``reindex`` / ``docs`` / ``snapshot`` / ``link`` / ``init`` / ``install-hooks`` /
  ``setup-*`` / ``federate`` / ``active-sync`` / ``sync-update`` / ``ci``) is refused
  BEFORE exec, and no argument of the new forms can smuggle one — proven by
  ``runner.calls == []`` and by the allowlist SET itself. The deliberately out-of-scope
  commands (``tui`` / ``ui`` / ``watch`` / ``mcp-serve`` / ``export`` / ``config-check``)
  are asserted too, so the BRIEF's scope decision is enforced rather than documented.
  This list grew in BOB-091.2, when the READ allowlist gained six more subcommands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    _BEADLOOM_SUBCOMMANDS,
    DisallowedCommandError,
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard

if TYPE_CHECKING:
    from pathlib import Path


class _ScriptedRunner:
    """Records argv; returns the queued stdout per call (never spawns a process)."""

    def __init__(self, *outputs: str) -> None:
        self.calls: list[list[str]] = []
        self._outputs = list(outputs) or [""]

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        index = min(len(self.calls) - 1, len(self._outputs) - 1)
        return self._outputs[index]


def _make(tmp_path: Path, runner: _ScriptedRunner) -> SubprocessRepoIntrospector:
    return SubprocessRepoIntrospector(PrivacyGuard(tmp_path), runner=runner)


_MERMAID = 'graph LR\n    memory["memory<br/>(feature)"]\n    memory -->|part_of| bob'
_C4_EMPTY = "C4Container"
_C4_FULL = 'C4Container\n    System_Boundary(b, "bob") {\n        Component(memory, "M")\n    }'


# --- the three allowed forms, exact argv ---------------------------------------


@pytest.mark.asyncio
async def test_overview_diagram_runs_bare_graph(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram()

    assert runner.calls == [["beadloom", "graph"]]
    assert diagram.mermaid.startswith("graph LR")
    assert diagram.form == "overview"
    assert diagram.requested == "overview"


@pytest.mark.asyncio
async def test_node_diagram_runs_graph_with_the_ref(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram("memory")

    assert runner.calls == [["beadloom", "graph", "memory"]]
    assert diagram.form == "node"


@pytest.mark.asyncio
async def test_node_diagram_with_depth_is_bounded(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    await intro.architecture_diagram("memory", depth=99)

    assert runner.calls == [["beadloom", "graph", "memory", "--depth", "5"]]


@pytest.mark.asyncio
async def test_components_diagram_runs_the_c4_form(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_C4_FULL)
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram(internals_of="bob-domain")

    assert runner.calls == [
        [
            "beadloom",
            "graph",
            "--format",
            "c4",
            "--level",
            "component",
            "--scope",
            "bob-domain",
        ]
    ]
    assert diagram.form == "components"
    assert diagram.requested == "components"


# --- the honest fallback --------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_components_view_falls_back_and_says_so(tmp_path: Path) -> None:
    # 🔴 Live behaviour: ``--scope memory`` prints a lone ``C4Container`` because a LEAF
    # has no internals. Bob must get a real diagram AND know it is the node form, so he
    # never presents links as internals.
    runner = _ScriptedRunner(_C4_EMPTY, _MERMAID)
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram(internals_of="memory")

    assert [call[1:] for call in runner.calls] == [
        ["graph", "--format", "c4", "--level", "component", "--scope", "memory"],
        ["graph", "memory"],
    ]
    assert diagram.form == "node"
    assert diagram.requested == "components"
    assert diagram.mermaid.startswith("graph LR")


@pytest.mark.asyncio
async def test_non_empty_components_view_does_not_fall_back(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_C4_FULL, _MERMAID)
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram(internals_of="bob-domain")

    assert len(runner.calls) == 1
    assert diagram.form == "components"


@pytest.mark.asyncio
async def test_unresolved_node_ref_yields_an_empty_diagram_not_a_guess(
    tmp_path: Path,
) -> None:
    # ``beadloom graph nosuchnode`` exits 0 with a bare ``graph LR`` header; the adapter
    # must pass that emptiness through (the capability answers honestly) and NOT quietly
    # draw the whole system instead.
    runner = _ScriptedRunner("graph LR")
    intro = _make(tmp_path, runner)

    diagram = await intro.architecture_diagram("nosuchnode")

    assert runner.calls == [["beadloom", "graph", "nosuchnode"]]
    assert diagram.mermaid.strip() == "graph LR"


# --- impact (``why``), digested -------------------------------------------------

_WHY = """\
╭─── Impact Analysis ───╮
│ memory (feature)      │
│ Memory module.        │
╰───────────────────────╯
Upstream (dependencies)
└── bob-domain (domain) ---- Domain layer umbrella.

Downstream (dependents)
└── capabilities (feature) ---- Capabilities module.
"""


@pytest.mark.asyncio
async def test_impact_runs_why_and_digests_the_output(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_WHY)
    intro = _make(tmp_path, runner)

    out = await intro.impact("memory")

    assert runner.calls == [["beadloom", "why", "memory"]]
    assert "bob-domain (domain)" in out
    assert "capabilities (feature)" in out
    for glyph in ("╭", "│", "└", "──"):
        assert glyph not in out


@pytest.mark.asyncio
async def test_impact_of_an_unknown_ref_is_empty_not_invented(tmp_path: Path) -> None:
    # ``beadloom why nosuchref`` writes its error to stderr; stdout is empty.
    runner = _ScriptedRunner("")
    intro = _make(tmp_path, runner)

    assert await intro.impact("nosuchref") == ""


# --- 🔴 the slot guard at the port surface --------------------------------------

_HOSTILE = [
    "--project=/etc",
    "--json",
    "memory; reindex",
    "$(beadloom reindex)",
    "../../etc/passwd",
    "memory extra",
    "-n",
]


@pytest.mark.parametrize("hostile", _HOSTILE)
@pytest.mark.asyncio
async def test_hostile_ref_never_reaches_a_subprocess(
    tmp_path: Path, hostile: str
) -> None:
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    with pytest.raises(ValueError, match="graph ref"):
        await intro.architecture_diagram(hostile)
    with pytest.raises(ValueError, match="graph ref"):
        await intro.architecture_diagram(internals_of=hostile)
    with pytest.raises(ValueError, match="graph ref"):
        await intro.impact(hostile)

    assert runner.calls == []


# --- 🔴 the read-only invariant: write commands stay INEXPRESSIBLE --------------

_WRITE_SUBCOMMANDS = [
    "reindex",
    "docs",
    "snapshot",
    "link",
    "init",
    "install-hooks",
    "setup-rules",
    "setup-mcp",
    "setup-agentic-flow",
    "setup-branch-protection",
    # BOB-091.2: the remaining write commands of the live CLI (``beadloom --help`` lists
    # 31). Enumerated so that growing the READ allowlist in .2 provably did not let one of
    # them in — ``sync-update`` in particular reads a lot like the allowed ``sync-check``.
    "setup-ai-techwriter",
    "federate",
    "active-sync",
    "sync-update",
    "ci",
]

# Deliberately OUT OF SCOPE rather than write commands (see the BRIEF): the interactive /
# server ones are meaningless in a chat, and ``export`` + ``snapshot compare`` are inert
# for Bob (federation is not this product; ``compare`` needs a ``snapshot save``, i.e. a
# write). They must be as inexpressible as the writes — a decision, not an oversight.
_OUT_OF_SCOPE_SUBCOMMANDS = [
    "tui",
    "ui",
    "watch",
    "mcp-serve",
    "export",
    "config-check",
]


@pytest.mark.parametrize("write_sub", _WRITE_SUBCOMMANDS)
@pytest.mark.asyncio
async def test_no_beadloom_write_subcommand_is_expressible(
    tmp_path: Path, write_sub: str
) -> None:
    # Defence in depth through the raw ``_run`` seam: the allowlist is the gate, so a
    # write subcommand is refused before exec no matter who asks.
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", write_sub)

    assert runner.calls == []


@pytest.mark.parametrize("out_of_scope", _OUT_OF_SCOPE_SUBCOMMANDS)
@pytest.mark.asyncio
async def test_no_out_of_scope_beadloom_subcommand_is_expressible(
    tmp_path: Path, out_of_scope: str
) -> None:
    # The scope decision is enforced, not just documented: an interactive/server command
    # or an inert artifact command is refused before exec, like a write.
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", out_of_scope)

    assert runner.calls == []


@pytest.mark.parametrize(
    "write_sub", [*_WRITE_SUBCOMMANDS, *_OUT_OF_SCOPE_SUBCOMMANDS]
)
def test_no_write_subcommand_is_in_the_allowlist_at_all(write_sub: str) -> None:
    # The structural half: the allowlist SET itself never names a write command, so the
    # refusal above cannot be an artefact of one code path.
    assert write_sub not in _BEADLOOM_SUBCOMMANDS


_OFF_FORM_GRAPH_ARGS: list[tuple[str, ...]] = [
    ("--json",),
    ("--project", "/etc"),
    ("--format", "c4-plantuml"),
    ("--format", "c4", "--level", "container", "--scope", "bob"),
    ("memory", "--depth", "0"),
    ("memory", "--depth", "9"),
    ("memory", "--depth", "abc"),
    ("memory", "--json"),
    ("memory", "social"),
    ("memory; reindex",),
    ("--scope", "bob"),
    ("--depth", "2"),
]


@pytest.mark.parametrize("args", _OFF_FORM_GRAPH_ARGS)
@pytest.mark.asyncio
async def test_off_form_graph_arguments_are_refused(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    # The forms are a fixed allowlist checked BEFORE exec: no flag passthrough, so a
    # model cannot reach another project (``--project``), another format, or an
    # unbounded depth even by calling the raw seam.
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", "graph", *args)

    assert runner.calls == []


_OFF_FORM_WHY_ARGS: list[tuple[str, ...]] = [
    (),
    ("memory", "extra"),
    ("memory; reindex",),
    ("--project=/etc",),
    ("../../etc",),
]


@pytest.mark.parametrize("args", _OFF_FORM_WHY_ARGS)
@pytest.mark.asyncio
async def test_off_form_why_arguments_are_refused(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    runner = _ScriptedRunner(_WHY)
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", "why", *args)

    assert runner.calls == []


@pytest.mark.asyncio
async def test_allowed_graph_forms_pass_the_guard(tmp_path: Path) -> None:
    # The positive side of the same guard: exactly the three planned shapes run.
    runner = _ScriptedRunner(_MERMAID)
    intro = _make(tmp_path, runner)

    await intro._run("beadloom", "graph")
    await intro._run("beadloom", "graph", "memory")
    await intro._run("beadloom", "graph", "memory", "--depth", "3")
    await intro._run(
        "beadloom", "graph", "--format", "c4", "--level", "component", "--scope", "bob"
    )

    assert len(runner.calls) == 4
