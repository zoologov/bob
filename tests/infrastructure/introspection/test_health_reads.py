# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The read-only project-health seam of the introspector (BOB-091.2).

Slice 1 gave Bob the architecture graph (``graph`` / ``why``); this is the rest of the
READ-ONLY beadloom — ``status`` / ``prime`` / ``doctor`` / ``sync-check`` / ``lint`` /
``diff`` — behind ONE port method. The module drives it through the recording-fake
subprocess boundary (nothing spawns) and asserts:

* the EXACT argv of each of the six allowed forms, including 🔴 ``lint --no-reindex
  --strict``: a plain ``beadloom lint`` REINDEXES, i.e. WRITES the index, so the flag is
  part of the read-only invariant and not a preference;
* the reports come back DIGESTED (585 pair lines are not a chat message);
* 🔴 a non-zero exit code is NOT a failure on this path: ``lint`` exits 1 on a violation,
  ``sync-check`` 2 on a stale pair and ``diff`` 1 on a change — each is a RESULT, and the
  answer must carry the verdict rather than "не смог посмотреть";
* the ``diff`` git-ref slot is validated before exec (a flag / path / range / shell
  metacharacter never reaches argv), proven by ``runner.calls == []``;
* every off-form shape is refused before exec — including ``lint --strict`` WITHOUT
  ``--no-reindex`` and ``prime --update`` (which rewrites ``AGENTS.md``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
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


# Verbatim shapes of the live CLI (captured in this repo before implementation).
_STATUS = (
    "╭───────────── Beadloom v2.1.0 ─────────────╮\n"
    "│ Last reindex: 2026-08-05T16:43:45+00:00   │\n"
    "╰───────────────────────────────────────────╯\n"
    "\n  Nodes: 22    Edges: 105    Docs: 23\n"
)
_DOCTOR = "  [ok] All nodes have summaries.\n  [warn] Package drift: claimed but missing\n"
_SYNC_STALE = (
    "  [ok] bob: architecture.md <-> src/bob/one.py\n"
    "  [stale] bob: architecture.md <-> src/bob/two.py (hash_changed)\n"
)
_LINT_PORCELAIN = "some-rule:forbid_import:error:src/bob/two.py:2::\n"
_DIFF_CHANGED = (
    "Graph diff (since HEAD~1):\n\nNodes:\n  + interactive (feature)\n\n"
    "1 added, 0 changed, 0 removed nodes; 1 added, 0 removed edges\n"
)
_PRIME = (
    "# Project: bob\n\nArchitecture: 3 domains, 2 services\n\n"
    "## Architecture Rules\n- one (require): x\n- two (require): y\n\n"
    "## Domains\n- bob-domain: the domain layer\n"
)


# --- the six allowed forms, exact argv ------------------------------------------


@pytest.mark.parametrize(
    ("check", "argv"),
    [
        ("status", ["beadloom", "status"]),
        ("prime", ["beadloom", "prime"]),
        ("doctor", ["beadloom", "doctor"]),
        ("sync-check", ["beadloom", "sync-check"]),
        ("lint", ["beadloom", "lint", "--no-reindex", "--strict"]),
        ("diff", ["beadloom", "diff", "--since", "HEAD"]),
    ],
)
@pytest.mark.asyncio
async def test_each_check_runs_its_exact_fixed_form(
    tmp_path: Path, check: str, argv: list[str]
) -> None:
    runner = _ScriptedRunner("ok\n")
    intro = _make(tmp_path, runner)

    health = await intro.project_health(check)

    assert runner.calls == [argv]
    assert health.check == check


@pytest.mark.asyncio
async def test_lint_never_reindexes_on_bobs_path(tmp_path: Path) -> None:
    """🔴 A plain ``beadloom lint`` writes the index — measured on the real CLI."""
    runner = _ScriptedRunner("0 violations, 224 rules evaluated\n")
    intro = _make(tmp_path, runner)

    await intro.project_health("lint")

    assert runner.calls == [["beadloom", "lint", "--no-reindex", "--strict"]]


@pytest.mark.asyncio
async def test_diff_runs_the_given_git_ref(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_DIFF_CHANGED)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("diff", since="features/BOB-091")

    assert runner.calls == [
        ["beadloom", "diff", "--since", "features/BOB-091"]
    ]
    assert "1 added, 0 changed, 0 removed nodes" in health.report


@pytest.mark.asyncio
async def test_a_paraphrased_check_still_runs_the_canonical_form(
    tmp_path: Path,
) -> None:
    runner = _ScriptedRunner(_SYNC_STALE)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("доки")

    assert runner.calls == [["beadloom", "sync-check"]]
    assert health.check == "sync-check"


# --- the reports come back digested, not as a terminal dump ---------------------


@pytest.mark.asyncio
async def test_status_comes_back_without_terminal_graphics(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_STATUS)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("status")

    assert "Nodes: 22" in health.report
    for glyph in ("╭", "│", "╰", "─"):
        assert glyph not in health.report


@pytest.mark.asyncio
async def test_sync_check_comes_back_as_counts_plus_the_stale_pairs(
    tmp_path: Path,
) -> None:
    runner = _ScriptedRunner(_SYNC_STALE)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("sync-check")

    assert "свежих 1, устаревших 1" in health.report
    assert "src/bob/two.py" in health.report
    assert "src/bob/one.py" not in health.report


@pytest.mark.asyncio
async def test_prime_comes_back_with_the_rule_list_collapsed(tmp_path: Path) -> None:
    runner = _ScriptedRunner(_PRIME)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("prime")

    assert "Правил архитектуры: 2" in health.report
    assert "one (require)" not in health.report


@pytest.mark.asyncio
async def test_an_empty_report_stays_empty(tmp_path: Path) -> None:
    # The caller answers honestly; the adapter must not invent a report.
    runner = _ScriptedRunner("")
    intro = _make(tmp_path, runner)

    assert (await intro.project_health("doctor")).report == ""


# --- 🔴 the count must be the TRUE count, not "as much as fitted in the cap" ----


@pytest.mark.asyncio
async def test_a_huge_report_is_condensed_before_the_output_cap(tmp_path: Path) -> None:
    """🔴 Found by running the real CLI through this path, not by a fake.

    ``sync-check`` prints 48 KB in this repo while the introspector caps raw output at
    20 000 chars — so the digest was counting only the pairs that FITTED and calmly
    reporting "274 pairs" instead of 585. A wrong number stated confidently is worse than
    a dump: condensing therefore happens BEFORE the cap, and the cap only ever guards the
    already-short answer.
    """
    pairs = 600
    huge = "".join(
        f"  [ok] bob: architecture.md <-> src/bob/some/module_{index}.py\n"
        for index in range(pairs)
    )
    assert len(huge) > 20_000, "фикстура должна превышать кап вывода"
    runner = _ScriptedRunner(huge)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("sync-check")

    assert f"Пар док↔код: {pairs}" in health.report


@pytest.mark.asyncio
async def test_a_huge_prime_counts_every_rule(tmp_path: Path) -> None:
    rules = 400
    huge = "# Project: bob\n\n## Architecture Rules\n" + "".join(
        f"- rule-number-{index} (forbid_import): длинное описание правила проекта\n"
        for index in range(rules)
    )
    assert len(huge) > 20_000
    runner = _ScriptedRunner(huge)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("prime")

    assert f"Правил архитектуры: {rules}." in health.report


@pytest.mark.asyncio
async def test_a_huge_impact_is_condensed_before_the_output_cap(
    tmp_path: Path,
) -> None:
    # The slice-1 read has the same shape of risk (``why`` prints 14 KB today, one graph
    # away from the cap), so it condenses first too — asserted, not assumed.
    upstream = "".join(
        f"├── node-{index} (feature) ---- подробное описание узла номер {index}\n"
        for index in range(500)
    )
    raw = f"node (feature)\nUpstream (dependencies)\n{upstream}"
    assert len(raw) > 20_000
    runner = _ScriptedRunner(raw)
    intro = _make(tmp_path, runner)

    out = await intro.impact("node")

    # Every direct dependency was SEEN (the list is capped at a dozen, but the count of
    # what it hid is honest), so the answer cannot be short because the input was cut.
    assert "и ещё 488" in out


# --- 🔴 a non-zero exit code is a RESULT, not a failure -------------------------


@pytest.mark.asyncio
async def test_a_lint_violation_answers_with_the_verdict(tmp_path: Path) -> None:
    """``lint --strict`` exits 1 here; the answer must be the violation, not an error."""
    runner = _ScriptedRunner(_LINT_PORCELAIN)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("lint")

    assert "Нарушений: 1" in health.report
    assert "some-rule" in health.report
    assert "src/bob/two.py:2" in health.report


@pytest.mark.asyncio
async def test_a_stale_sync_check_answers_with_the_stale_pair(tmp_path: Path) -> None:
    """``sync-check`` exits 2 here; "доки отстали" is the answer, not a tool failure."""
    runner = _ScriptedRunner(_SYNC_STALE)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("sync-check")

    assert "устаревших 1" in health.report


@pytest.mark.asyncio
async def test_a_changed_diff_answers_with_the_changes(tmp_path: Path) -> None:
    """``diff`` exits 1 when the graph changed; the changes ARE the answer."""
    runner = _ScriptedRunner(_DIFF_CHANGED)
    intro = _make(tmp_path, runner)

    health = await intro.project_health("diff", since="HEAD~1")

    assert "+ interactive (feature)" in health.report


# --- the guards: nothing hostile reaches argv -----------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "reindex",
        "docs",
        "link",
        "install-hooks",
        "setup-mcp",
        "ci",
        "prime --update",
        "--json",
        "status; reindex",
        "",
    ],
)
@pytest.mark.asyncio
async def test_a_check_outside_the_closed_list_never_runs(
    tmp_path: Path, hostile: str
) -> None:
    runner = _ScriptedRunner("ok\n")
    intro = _make(tmp_path, runner)

    with pytest.raises(ValueError, match="project-health check"):
        await intro.project_health(hostile)

    assert runner.calls == []


@pytest.mark.parametrize(
    "hostile",
    [
        "--project",
        "main; rm -rf /",
        "$(whoami)",
        "HEAD..main",
        "../../etc/passwd",
        "/etc/passwd",
        "main HEAD",
        "HEAD@{1}",
        "a" * 100,
    ],
)
@pytest.mark.asyncio
async def test_a_hostile_diff_ref_never_runs(tmp_path: Path, hostile: str) -> None:
    runner = _ScriptedRunner(_DIFF_CHANGED)
    intro = _make(tmp_path, runner)

    with pytest.raises(ValueError, match="git ref"):
        await intro.project_health("diff", since=hostile)

    assert runner.calls == []


_OFF_FORM_HEALTH_ARGS: list[tuple[str, tuple[str, ...]]] = [
    ("status", ("--json",)),
    ("status", ("--project", "/etc")),
    ("status", ("--debt-report",)),
    ("status", ("--fail-if", "errors>0")),
    # 🔴 --update REWRITES AGENTS.md: a write behind a read subcommand.
    ("prime", ("--update",)),
    ("prime", ("--json",)),
    ("doctor", ("--project", "/etc")),
    ("sync-check", ("--json",)),
    ("sync-check", ("--since", "HEAD")),
    ("sync-check", ("--report",)),
    # 🔴 --strict WITHOUT --no-reindex is the shape that would reindex (a write).
    ("lint", ("--strict",)),
    ("lint", ()),
    ("lint", ("--no-reindex",)),
    ("lint", ("--no-reindex", "--strict", "--format", "json")),
    ("lint", ("--fail-on-warn",)),
    ("diff", ()),
    ("diff", ("--since",)),
    ("diff", ("--since", "--project")),
    ("diff", ("--since", "HEAD", "--json")),
    ("diff", ("--json",)),
    ("diff", ("HEAD",)),
]


@pytest.mark.parametrize(("subcommand", "args"), _OFF_FORM_HEALTH_ARGS)
@pytest.mark.asyncio
async def test_off_form_health_arguments_are_refused(
    tmp_path: Path, subcommand: str, args: tuple[str, ...]
) -> None:
    # The forms are a fixed allowlist checked BEFORE exec: no flag passthrough, so even a
    # caller that skips the planner cannot widen them.
    runner = _ScriptedRunner("ok\n")
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", subcommand, *args)

    assert runner.calls == []


@pytest.mark.parametrize(
    ("subcommand", "args"),
    [
        ("status", ()),
        ("prime", ()),
        ("doctor", ()),
        ("sync-check", ()),
        ("lint", ("--no-reindex", "--strict")),
        ("diff", ("--since", "HEAD")),
        ("diff", ("--since", "features/BOB-091")),
        ("diff", ("--since", "7edfd7c")),
    ],
)
@pytest.mark.asyncio
async def test_allowed_health_forms_pass_the_guard(
    tmp_path: Path, subcommand: str, args: tuple[str, ...]
) -> None:
    # The positive half of the guard: the shapes the planner produces really do pass, so
    # the check cannot be "reject everything" (which would pass the negative tests too).
    runner = _ScriptedRunner("ok\n")
    intro = _make(tmp_path, runner)

    await intro._run("beadloom", subcommand, *args)

    assert runner.calls == [["beadloom", subcommand, *args]]
