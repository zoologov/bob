# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Real-CLI integration tests for SubprocessRepoIntrospector (BOB-031 .2).

The unit suite (``test_subprocess_introspector.py``) drives a deterministic FAKE
runner, so it can prove the *routing* but never that the routes actually ground
against the live tools. THIS module is the missing half: it runs the introspector
against the ACTUAL ``beadloom`` / ``bd`` binaries in this repo, through the real
``_ExecRunner`` (a real subprocess, no shell) — the regression net for the bug that
shipped before .1, where a natural question returned ``''`` (ungrounded).

Each test is guarded against environment flakiness: if ``beadloom`` / ``bd`` are not
on PATH or the repo is not initialised for them, the test ``pytest.skip``s with a
clear reason, so CI on a stripped checkout stays green. In THIS repo both tools are
present and initialised, so the tests actually run and must PASS.

🔴 BOB-112.11: the tests that drive ONLY the real ``beadloom`` carry
``@pytest.mark.real_beadloom``. CI installs the pinned beadloom and sets
``BOB_REQUIRE_REAL_BEADLOOM=1``, so there their skip is a FAILURE with the original reason
(``tests/support/real_beadloom_requirement.py``) — a ``why``/``diff`` that changed on a
version bump can no longer pass as a quiet skip. Not marked, on purpose: the ``bd`` tests
(CI has no tracker) and the ``diff`` test that needs an old commit (CI checks out one).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
    _ExecRunner,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard

pytestmark = pytest.mark.integration

# Repo root: this file is tests/infrastructure/introspection/<file>, so up three.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _binary_ready(binary: str, *probe: str) -> bool:
    """Whether ``binary`` is on PATH and a read-only probe call exits cleanly.

    The probe runs from the repo root (where ``.beads`` / ``.beadloom`` live) so an
    uninitialised checkout (binary present but no index) is detected and skipped
    rather than producing a misleading empty assertion failure.
    """
    if shutil.which(binary) is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 — fixed read-only argv, no shell
            [binary, *probe],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _real_introspector() -> SubprocessRepoIntrospector:
    """An introspector wired to the REAL exec runner against the live repo root."""
    # No ``runner=`` -> the default _ExecRunner (real create_subprocess_exec, no shell).
    return SubprocessRepoIntrospector(PrivacyGuard(_REPO_ROOT))


# --- 🔴 the whole point of this bead: free text actually GROUNDS ----------------


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_architecture_context_free_text_grounds_against_real_beadloom() -> None:
    """🔴 BOB-031: a natural free-text question returns a NON-empty grounded result.

    This is the regression the bead exists for: before .1, ``architecture_context``
    routed free text to ``beadloom ctx`` (which needs an exact ref) and a question
    like "memory" returned ``''``. Now it routes to ``beadloom search`` and grounds.
    """
    if not _binary_ready("beadloom", "search", "memory"):
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    intro = _real_introspector()

    out = await intro.architecture_context("memory")

    assert out.strip(), "free-text architecture question must ground (non-empty)"
    # Grounded in THIS repo's graph, not generic model prose: the search hit names a
    # real bob node/domain (the FTS index is over bob's own architecture docs).
    assert "bob" in out.lower()


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_architecture_context_ref_id_grounds_against_real_beadloom() -> None:
    """An exact ref-id question grounds via ``beadloom ctx`` (its native input)."""
    if not _binary_ready("beadloom", "ctx", "bob-application"):
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    intro = _real_introspector()

    out = await intro.architecture_context("bob-application")

    assert out.strip(), "an exact ref-id must ground via ctx"


# --- 🔴 listing closed tasks actually returns real closed beads -----------------


@pytest.mark.asyncio
async def test_list_tasks_closed_lists_real_closed_beads() -> None:
    """🔴 BOB-031: a "closed" query returns a NON-empty listing of real closed beads.

    Before .1, ``list_tasks`` only knew ``bd ready`` (currently empty-ish) + ``bd
    show``; "what's closed / recent / history" went nowhere. Now it routes to
    ``bd list --status closed`` and surfaces real ``bob-...`` ids.
    """
    if not _binary_ready("bd", "list", "--status", "closed"):
        pytest.skip("bd not on PATH or beads not initialised in this repo")
    intro = _real_introspector()

    out = await intro.list_tasks("закрытые задачи")

    assert out.strip(), "closed-task listing must be non-empty in this repo"
    # The listing names real closed bob beads (the repo has dozens of closed ones).
    assert "bob-" in out


@pytest.mark.asyncio
async def test_list_tasks_id_grounds_via_real_bd_show() -> None:
    """A bare bead id routes to the real ``bd show <id>`` and returns its detail."""
    if not _binary_ready("bd", "show", "bob-1av"):
        pytest.skip("bd not on PATH or bead bob-1av absent")
    intro = _real_introspector()

    out = await intro.list_tasks("bob-1av")

    assert "bob-1av" in out


# --- 🔴 empty -> bd ready works AND tooling-noise tail is stripped --------------


@pytest.mark.asyncio
async def test_list_tasks_empty_runs_real_bd_ready_with_noise_stripped() -> None:
    """🔴 BOB-031: an empty query runs the real ``bd ready`` and the Tip/legend tail
    is stripped from the live output (Bob must not riff on tooling chrome).

    ``bd ready`` prints a trailing status legend (``Status: ○ open …``); the denoise
    must remove it from the live stdout while keeping the real ready content.
    """
    if not _binary_ready("bd", "ready"):
        pytest.skip("bd not on PATH or beads not initialised in this repo")
    intro = _real_introspector()

    out = await intro.list_tasks("")

    # The legend / Tip chrome that bd appends must be gone from the live result...
    assert "Status: ○ open" not in out
    assert "💡" not in out
    assert "Tip:" not in out
    # ...but the trailing legend must be the ONLY thing dropped: real ready content
    # (the open bead under BOB-031) survives. (If the ready queue were truly empty the
    # body would still carry the "Ready: N issues" summary line, never the legend.)
    assert out.strip(), "bd ready output must retain real content after denoise"


# --- 🔴 BOB-090.A: the tracker ANSWERS on the live repo -------------------------
# These run against the REAL ``bd`` of this repository, because the whole defect was
# invisible to fake-runner tests: the routing was "correct" while ``bd search`` was
# off the allowlist, excluded closed issues by default, and the epic key was never
# cut out of the sentence. A fake proves the fake's contract (the BOB-084 lesson);
# only the live binary proves Bob stops saying "не существует".

_LIVE_EPIC_KEY = "BOB-087"  # a real, fully CLOSED epic of this repo
_LIVE_EPIC_ID = "bob-abk"  # ...whose bd identifier looks nothing like its key


def _tracker_has(*probe: str) -> bool:
    """Whether the live ``bd`` answers this read-only probe with real content."""
    if shutil.which("bd") is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 — fixed read-only argv, no shell
            ["bd", *probe],  # noqa: S607 — bd is resolved via PATH by design
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "bob-" in proc.stdout


@pytest.mark.asyncio
async def test_show_task_epic_key_grounds_via_real_search() -> None:
    """🔴 The live symptom: «GUPPI твердит, что BOB-087 не существует».

    ``bd show BOB-087`` really does print nothing (in bd the identifier is
    ``bob-abk``; the key lives in the TITLE), so the tool was not lying — it had no
    way to look. Now the empty ``show`` retries as a title search that includes
    closed issues, and the epic is found.
    """
    if not _tracker_has("search", _LIVE_EPIC_KEY, "--status", "all"):
        pytest.skip(f"live tracker has no {_LIVE_EPIC_KEY} tasks")
    intro = _real_introspector()

    out = await intro.show_task(_LIVE_EPIC_KEY)

    assert out.strip(), "an epic key must not answer 'не существует'"
    assert _LIVE_EPIC_ID in out


@pytest.mark.asyncio
async def test_list_tasks_epic_key_in_a_phrase_grounds_and_stays_short() -> None:
    """«расскажи про нашу задачу BOB-087» finds the epic AND fits in a chat message.

    bd matches a title SUBSTRING, so the phrase itself matches nothing — the key has
    to be cut out. The key then matches dozens of tasks, so the live answer must come
    back digested, not as a forty-line dump (BOB-086).
    """
    if not _tracker_has("search", _LIVE_EPIC_KEY, "--status", "all"):
        pytest.skip(f"live tracker has no {_LIVE_EPIC_KEY} tasks")
    intro = _real_introspector()

    out = await intro.list_tasks(f"расскажи про нашу задачу {_LIVE_EPIC_KEY}")

    assert _LIVE_EPIC_ID in out
    assert "Найдено:" in out  # the digest summary, not the raw listing
    assert len(out.splitlines()) <= 12


@pytest.mark.asyncio
async def test_list_tasks_open_lists_real_open_beads() -> None:
    """🔴 The live symptom: «какие открыты?» -> «Пусто, GUPPI выдал чистый лист»."""
    if not _tracker_has("list", "--status", "open"):
        pytest.skip("live tracker has no open beads")
    intro = _real_introspector()

    out = await intro.list_tasks("какие открыты?")

    assert out.strip(), "an open-task question must not answer 'пусто'"
    assert "bob-" in out


@pytest.mark.asyncio
async def test_real_run_is_sanitised_and_bounded() -> None:
    """A live run still passes through the privacy sanitiser + char cap (cheap probe).

    Uses a real ``bd list --status closed`` (large output) under a tiny cap to prove
    the bound is enforced end-to-end with the real runner, not just with the fake.
    """
    if not _binary_ready("bd", "list", "--status", "closed"):
        pytest.skip("bd not on PATH or beads not initialised in this repo")
    intro = SubprocessRepoIntrospector(
        PrivacyGuard(_REPO_ROOT), max_output_chars=200
    )

    out = await intro.list_tasks("закрытые")

    # Cap (200) + the short truncation marker, nothing unbounded.
    assert len(out) <= 200 + 64


# --- 🔴 BOB-091.1: the architecture reads against the REAL beadloom -------------
# A fake runner proves the FAKE's contract (CLAUDE.md §0.3 п.4). These run the LIVE
# ``beadloom graph`` / ``why`` in this repo, so the two facts a fake cannot know are
# actually asserted: a ``--scope`` on a graph LEAF really does print an empty diagram
# (the fallback fires), and the real 197-line ``why`` panel really does condense.


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_overview_diagram_is_real_mermaid_of_this_repo() -> None:
    if not _binary_ready("beadloom", "graph"):
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    intro = _real_introspector()

    diagram = await intro.architecture_diagram()

    assert diagram.form == "overview"
    assert diagram.mermaid.startswith("graph")
    # Real nodes of THIS repo's graph, not a template.
    assert "memory" in diagram.mermaid
    assert "capabilities" in diagram.mermaid


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_node_diagram_with_depth_is_real_and_bounded() -> None:
    if not _binary_ready("beadloom", "graph", "memory", "--depth", "1"):
        pytest.skip("beadloom graph --depth unavailable")
    intro = _real_introspector()

    diagram = await intro.architecture_diagram("memory", depth=1)

    assert diagram.form == "node"
    assert "memory" in diagram.mermaid
    # A one-node neighbourhood is smaller than the whole map.
    overview = await intro.architecture_diagram()
    assert len(diagram.mermaid) < len(overview.mermaid)


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_components_diagram_of_a_container_is_real_c4() -> None:
    if not _binary_ready(
        "beadloom", "graph", "--format", "c4", "--level", "component", "--scope",
        "bob-domain",
    ):
        pytest.skip("beadloom c4 component view unavailable")
    intro = _real_introspector()

    diagram = await intro.architecture_diagram(internals_of="bob-domain")

    assert diagram.form == "components"
    assert "C4" in diagram.mermaid
    assert "Component(" in diagram.mermaid


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_components_of_a_leaf_really_falls_back_on_the_live_cli() -> None:
    """🔴 The fact only the REAL CLI reveals: a leaf has no internals to draw.

    ``graph --format c4 --level component --scope memory`` prints a lone
    ``C4Container`` header — an empty picture. A fake runner would happily return a
    populated diagram and this fallback would look dead while the owner got nothing.
    """
    if not _binary_ready("beadloom", "graph", "memory"):
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    intro = _real_introspector()

    diagram = await intro.architecture_diagram(internals_of="memory")

    assert diagram.requested == "components"
    assert diagram.form == "node", "a leaf scope must degrade to that node's links"
    assert "memory" in diagram.mermaid


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_impact_of_a_real_node_is_condensed_not_a_screenshot() -> None:
    if not _binary_ready("beadloom", "why", "memory"):
        pytest.skip("beadloom why unavailable")
    intro = _real_introspector()

    out = await intro.impact("memory")

    assert out.startswith("memory (feature)")
    assert "Зависит от:" in out
    assert "Влияет на:" in out
    # The live panel is ~197 lines / 14 KB; the answer is a handful of lines.
    assert len(out.splitlines()) <= 5
    for glyph in ("╭", "│", "├", "└"):
        assert glyph not in out


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_impact_of_an_unknown_ref_stays_empty_on_the_live_cli() -> None:
    if not _binary_ready("beadloom", "graph"):
        pytest.skip("beadloom not on PATH or repo not indexed for it")
    intro = _real_introspector()

    assert await intro.impact("nosuchnode") == ""


# --- 🔴 BOB-091.2: the project-health reads against the REAL beadloom -----------
# The exit-code trap of this slice is invisible to a fake: ``lint`` exits 1 on a
# violation, ``sync-check`` 2 on a stale pair, ``diff`` 1 on a change — a runner that
# treated a non-zero status as failure would make Bob say "не смог посмотреть" instead of
# "доки отстали". The other live-only fact is the SIZE: ``sync-check`` prints 48 KB / 585
# pair lines in this repo and ``prime`` 39 KB, so only a real run proves the digest works.

# A commit of this repo whose graph YAML differs from its parent (the ``interactive`` node
# was added there), used to reach the exit-1 branch of ``diff`` without touching anything.
_GRAPH_CHANGING_COMMIT = "66aa620"


def _report_ready(*argv: str) -> bool:
    """Whether the live ``beadloom`` produces this report — regardless of exit status.

    🔴 :func:`_binary_ready` requires ``rc == 0``, which is WRONG for the verdict
    commands: ``lint --strict`` exits 1 on a violation and ``sync-check`` exits 2 on a
    stale pair. Using it here made three of these tests skip silently on their very first
    run (this repo had a stale doc pair at that moment) — a readiness probe that falls into
    the exact trap the tests exist to catch. Readiness is therefore "it printed a report".
    """
    if shutil.which("beadloom") is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 — fixed read-only argv, no shell
            ["beadloom", *argv],  # noqa: S607 — resolved via PATH by design
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(proc.stdout.strip())


def _git_has(ref: str) -> bool:
    """Whether ``ref`` resolves in this checkout (a shallow clone may not have it)."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed read-only argv, no shell
            ["git", "rev-parse", "--verify", "--quiet", ref],  # noqa: S607
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_status_of_this_repo_is_real_numbers_without_the_rich_frames() -> None:
    if not _report_ready("status"):
        pytest.skip("beadloom status unavailable")
    intro = _real_introspector()

    health = await intro.project_health("status")

    assert health.check == "status"
    assert "Nodes:" in health.report
    assert "Last reindex:" in health.report
    for glyph in ("╭", "│", "╰", "─"):
        assert glyph not in health.report


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_prime_of_this_repo_collapses_the_224_rule_list() -> None:
    """🔴 Live ``prime`` is ~39 KB, of which ~224 lines are the rule list."""
    if not _report_ready("prime"):
        pytest.skip("beadloom prime unavailable")
    intro = _real_introspector()

    health = await intro.project_health("prime")

    assert "Architecture:" in health.report
    assert re.search(r"Правил архитектуры: \d{2,}", health.report), health.report[:400]
    # The rules are a COUNT now: not one of them is named.
    assert "domain-needs-parent" not in health.report
    # ...and the agent-instruction chrome never reaches Bob's context.
    assert "Agent Instructions" not in health.report
    assert len(health.report) < 6000, "39 KB must not reach a chat message"


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_doctor_of_this_repo_counts_its_checks() -> None:
    if not _report_ready("doctor"):
        pytest.skip("beadloom doctor unavailable")
    intro = _real_introspector()

    health = await intro.project_health("doctor")

    assert re.search(r"Проверок графа пройдено: \d+ из \d+\.", health.report)
    assert "[ok]" not in health.report


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_sync_check_of_this_repo_condenses_585_pair_lines() -> None:
    """🔴 Live ``sync-check`` prints 48 KB / 585 pair lines; the answer is a few lines."""
    if not _report_ready("sync-check"):
        pytest.skip("beadloom sync-check unavailable")
    intro = _real_introspector()

    health = await intro.project_health("sync-check")

    assert re.search(r"Пар док↔код: \d{2,}", health.report), health.report[:400]
    assert "не для всех узлов" in health.report, "the pairing caveat must survive"
    assert len(health.report.splitlines()) <= 55


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_sync_check_counts_every_pair_the_live_cli_printed() -> None:
    """🔴 The count must be the TRUE count — the defect only a live run exposed.

    The introspector caps raw output at 20 000 chars while the live ``sync-check`` prints
    ~48 KB, so a digest applied AFTER the cap counted only the pairs that FITTED and
    answered "274 пары" for 585. Here the expected number is taken from the CLI itself
    rather than hardcoded, so the test keeps biting as the repo grows.
    """
    if shutil.which("beadloom") is None:
        pytest.skip("beadloom not on PATH")
    proc = subprocess.run(
        ["beadloom", "sync-check"],  # noqa: S607 — resolved via PATH by design
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    expected = sum(
        1
        for line in proc.stdout.splitlines()
        if line.strip().startswith(("[ok]", "[stale]"))
    )
    if not expected:
        pytest.skip("live sync-check printed no pairs")
    intro = _real_introspector()

    health = await intro.project_health("sync-check")

    assert f"Пар док↔код: {expected}" in health.report


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_prime_keeps_its_tail_sections_on_the_live_cli() -> None:
    """🔴 The same cap silently ate ``prime``'s MOST useful part.

    ``prime`` prints ~39 KB with the rule list FIRST and the domains / stale-docs / lint
    sections LAST, so a 20 000-char cap applied before the digest threw away exactly what
    a person asks for. Condensing before the cap keeps the tail.
    """
    if not _report_ready("prime"):
        pytest.skip("beadloom prime unavailable")
    intro = _real_introspector()

    health = await intro.project_health("prime")

    assert "Domains:" in health.report
    assert "bob-domain" in health.report
    assert "Lint Violations:" in health.report


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_sync_check_verdict_is_stable_across_two_live_runs() -> None:
    """🔴 The read must not ERASE the signal a human gate later depends on.

    ``sync-check`` does touch the index file, so the question is whether a second run
    still reports the same staleness — if it re-baselined, Bob looking at the docs would
    quietly hide drift from the pre-commit hook. Measured here on the live CLI: the
    verdict is identical across runs.
    """
    if not _report_ready("sync-check"):
        pytest.skip("beadloom sync-check unavailable")
    intro = _real_introspector()

    first = await intro.project_health("sync-check")
    second = await intro.project_health("sync-check")

    assert first.report.splitlines()[0] == second.report.splitlines()[0]


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_lint_of_this_repo_answers_with_a_verdict_and_the_caveat() -> None:
    if not _report_ready("lint", "--no-reindex", "--strict"):
        pytest.skip("beadloom lint unavailable")
    intro = _real_introspector()

    health = await intro.project_health("lint")

    # Either shape of the live CLI is a verdict: the clean summary or the digested
    # porcelain tuples. What must never happen is an empty answer.
    assert "violations" in health.report or "Нарушений:" in health.report
    assert "сохранённому индексу" in health.report


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_lint_read_does_not_write_the_index_on_the_live_cli() -> None:
    """🔴 The find of this slice: a PLAIN ``beadloom lint`` reindexes, i.e. WRITES.

    Bob's form carries ``--no-reindex`` for exactly that reason, and this test measures
    the invariant on the real binary instead of trusting the flag: the index file's
    content is byte-identical after the read.
    """
    index = _REPO_ROOT / ".beadloom" / "beadloom.db"
    if not index.exists() or not _report_ready("lint", "--no-reindex"):
        pytest.skip("beadloom index unavailable")
    before = hashlib.sha256(index.read_bytes()).hexdigest()
    intro = _real_introspector()

    await intro.project_health("lint")

    assert hashlib.sha256(index.read_bytes()).hexdigest() == before


# 🔴 The read-only invariant is measured on EVERY form, not just ``lint`` (review Minor-5):
# if a future beadloom made ``status`` or ``doctor`` write, only a per-form measurement
# would notice. ``sync-check`` is the ONE documented exception: its bytes change on every
# run (SQLite page/header churn from opening the index read-write), while the DATA does
# not — measured table by table, all 22 table digests are identical around the call, and
# the verdict itself is stable across runs (asserted separately just above). So the
# exception is about bytes, not about content, and it is nailed down here rather than left
# as a silent hole.
_INDEX_WRITING_FORMS = frozenset({"sync-check"})


@pytest.mark.real_beadloom
@pytest.mark.parametrize(
    "check", ["status", "prime", "doctor", "lint", "diff", "sync-check"]
)
@pytest.mark.asyncio
async def test_no_read_form_but_sync_check_touches_the_index_bytes(check: str) -> None:
    index = _REPO_ROOT / ".beadloom" / "beadloom.db"
    if not index.exists() or shutil.which("beadloom") is None:
        pytest.skip("beadloom index unavailable")
    intro = _real_introspector()
    # A first call absorbs the one-off churn a "warm" index shows after other commands,
    # so the measurement is about THIS form, not about whatever ran before it.
    await intro.project_health(check)
    before = hashlib.sha256(index.read_bytes()).hexdigest()

    await intro.project_health(check)

    changed = hashlib.sha256(index.read_bytes()).hexdigest() != before
    assert changed == (check in _INDEX_WRITING_FORMS), (
        f"{check}: изменение байтов индекса = {changed}, "
        f"ожидалось {check in _INDEX_WRITING_FORMS}"
    )


# --- 🔴 BOB-091.4: a PLANTED graph-level violation, on the live CLI --------------
#
# Critical-1's root cause was not a typo, it was the fixture: slice 2 captured ONE live
# violation (a ``forbid_import``, the only kind that carries a file and a line) and the
# verdict was built to that sample, so every rule about a NODE or an EDGE — cardinality,
# cycle, require, layer, which print EMPTY file/line slots — was invisible and the raw
# machine tuple went out to the person instead. §0.3 п.4 in its sharpest form. The fix is
# therefore gated on a REAL beadloom run over a throw-away project that breaks all three
# shapes at once, with the expected count taken from the CLI itself.

_PROBE_GRAPH = """nodes:
  - ref_id: probe
    kind: service
    source: src/
    tags: [layer-runtime]
    summary: 'Probe service root.'
  - ref_id: alpha
    kind: feature
    source: src/alpha/
    tags: [module-vertical]
    summary: 'Alpha module.'
  - ref_id: beta
    kind: feature
    source: src/beta/
    tags: [module-vertical]
    summary: 'Beta module.'
edges:
  - {src: probe, dst: probe, kind: part_of}
  - {src: alpha, dst: probe, kind: part_of}
  - {src: beta, dst: probe, kind: part_of}
"""

_PROBE_RULES = """version: 3
rules:
  - name: alpha-no-beta-internals
    description: "a FILE rule: fills file + line"
    severity: error
    forbid_import: {from: "src/alpha/*", to: "beta/internals*"}
  - name: no-dependency-cycles
    description: "an EDGE rule: fills from + to, no file"
    severity: error
    forbid_cycles: {edge_kind: depends_on}
  - name: no-monster-modules
    description: "a NODE rule: fills from only, no file"
    severity: warn
    check:
      for: {kind: feature}
      max_symbols: 1
"""

_PROBE_ALPHA = """from beta.internals import beta_thing


def alpha_one() -> int:
    return beta_thing()


def alpha_two() -> int:
    return 2
"""

_PROBE_BETA = """from alpha.mod import alpha_two


def beta_thing() -> int:
    return alpha_two()


def beta_other() -> int:
    return 3
"""


def _write_probe_project(root: Path) -> Path:
    """Write (and index) a throw-away beadloom project that breaks all three rule shapes."""
    graph = root / ".beadloom" / "_graph"
    graph.mkdir(parents=True)
    (graph / "graph.yml").write_text(_PROBE_GRAPH, encoding="utf-8")
    (graph / "rules.yml").write_text(_PROBE_RULES, encoding="utf-8")
    (root / "src" / "alpha").mkdir(parents=True)
    (root / "src" / "beta").mkdir(parents=True)
    (root / "src" / "alpha" / "mod.py").write_text(_PROBE_ALPHA, encoding="utf-8")
    (root / "src" / "beta" / "internals.py").write_text(_PROBE_BETA, encoding="utf-8")
    # Fixed argv, no shell; writes only inside tmp_path.
    subprocess.run(
        ["beadloom", "reindex"],  # noqa: S607 — resolved via PATH by design
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return root


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_a_planted_node_and_edge_violation_reaches_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Critical-1: the count is the CLI's count, and no machine tuple is echoed."""
    if shutil.which("beadloom") is None:
        pytest.skip("beadloom not on PATH")
    project = _write_probe_project(tmp_path / "probe")
    raw = subprocess.run(  # fixed read-only argv, no shell
        ["beadloom", "lint", "--no-reindex", "--strict"],  # noqa: S607 — via PATH
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    printed = [line for line in raw.stdout.splitlines() if line.strip()]
    if not printed:
        pytest.skip("beadloom lint printed nothing for the probe project")
    # The fixture itself is asserted: the LIVE tool really does print empty file/line
    # slots — the shape the pre-fix pattern could not see.
    assert any(line.split(":")[3] == "" for line in printed), raw.stdout
    monkeypatch.chdir(project)
    intro = SubprocessRepoIntrospector(PrivacyGuard(project))

    health = await intro.project_health("lint")

    # Taken from the CLI, never hardcoded: the number Bob says IS the number of lines the
    # linter printed, whatever the shapes among them.
    assert f"Нарушений: {len(printed)}." in health.report, health.report
    # The cycle names BOTH ends — "alpha" alone would not be the fact that matters.
    assert "alpha → beta" in health.report
    assert "сохранённому индексу" in health.report
    for line in printed:
        assert line not in health.report, "сырой porcelain не выходит наружу"


@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_diff_without_graph_changes_answers_honestly() -> None:
    if not _report_ready("diff", "--since", "HEAD"):
        pytest.skip("beadloom diff unavailable")
    intro = _real_introspector()

    health = await intro.project_health("diff")

    assert health.check == "diff"
    assert health.report.strip(), "diff must always say something"


# ``real_beadloom`` since BOB-112.12: besides the binary it needs ``66aa620~1`` in the checkout.
# On a shallow CI checkout (depth 1) it skipped silently on every run (measured on the runner:
# "not in this checkout"), so ci.yml now checks out the full history (``fetch-depth: 0``) and
# the SKIP on the runner is a FAILED — a missing commit there is a broken checkout, not a
# legitimate reason to not run the one test that proves the exit-code trap on the real CLI.
@pytest.mark.real_beadloom
@pytest.mark.asyncio
async def test_a_graph_changing_diff_exits_nonzero_and_still_answers() -> None:
    """🔴 The exit-code trap, proven on the REAL CLI: ``diff`` exits 1 on a change.

    A fake runner cannot show this — it has no exit status. Here the live binary really
    does return 1 (verified by hand: ``rc=1`` with the change listing on stdout), and the
    answer carries the CHANGES, not "не смог посмотреть".
    """
    ref = f"{_GRAPH_CHANGING_COMMIT}~1"
    if not _git_has(ref) or shutil.which("beadloom") is None:
        pytest.skip(f"{ref} not in this checkout")
    intro = _real_introspector()

    health = await intro.project_health("diff", since=ref)

    assert "Graph diff" in health.report
    assert "interactive" in health.report
    # The counts line is the payload and it lives at the END of the report.
    assert "added" in health.report.splitlines()[-1]


@pytest.mark.asyncio
async def test_the_real_runner_returns_stdout_of_a_nonzero_exit() -> None:
    """🔴 The structural half of the exit-code contract, on a REAL subprocess.

    The verdict-bearing commands exit 1/2 by design, so the transport must hand back
    their stdout regardless of status. Asserted against a real process (not a fake) so
    the guarantee is about the transport actually in use.
    """
    out = await _ExecRunner()(
        [sys.executable, "-c", "import sys; print('verdict'); sys.exit(2)"],
        timeout=30,
    )

    assert out.strip() == "verdict"
