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
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.domain.introspection.privacy_guard import PrivacyGuard
from bob.infrastructure.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)

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
