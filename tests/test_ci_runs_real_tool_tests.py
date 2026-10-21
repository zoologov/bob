# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 In CI the tests against the REAL beadloom binary run instead of skipping (BOB-112.6).

About thirty introspection, diagram and tool-health tests drive the real ``beadloom``
binary (``why``/``diff``/``lint``/``sync-check``/``doctor``/``graph``) and SKIP when it is
not on PATH or the repo has no index. ``ci.yml`` ran ``Pytest`` BEFORE installing beadloom,
so on the runner every one of them was silently skipped: the review measured 331 passed /
37 skipped without beadloom on PATH versus 368/368 with the release 9.0.0. The ``why`` /
``diff`` format of the pinned build — the one ``impact_digest``/``health_digest`` were fixed
for and the one installed on the VPS — was never checked by CI, while the run read green.

This guard turns that skip into a failure. It judges not the order of steps in the YAML (the
shape of a text, ``CLAUDE.md`` §0.3 item 12) but the runner's state while pytest is already
running: the binary is on PATH, the index exists, and the binary is the build the job
declares (``BEADLOOM_VERSION``). Outside GitHub Actions it SKIPs with a reason saying the
runner was NOT checked — never a green: locally PATH is the developer's business, and no
verdict about the runner is taken from here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INDEX = _REPO_ROOT / ".beadloom" / "beadloom.db"
# The job-level variable ci.yml installs beadloom from: one source for the pin and its check.
_PINNED_VERSION_ENV = "BEADLOOM_VERSION"
_VERSION_TIMEOUT_S = 60


def _on_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def test_ci_runner_has_the_pinned_beadloom_and_its_index_while_pytest_runs() -> None:
    if not _on_github_actions():
        pytest.skip(
            "not GitHub Actions: whether the runner holds the pinned beadloom and its "
            "index while pytest runs was NOT checked"
        )

    binary = shutil.which("beadloom")
    assert binary is not None, (
        "beadloom is not on PATH while pytest runs, so the real-binary tests skip "
        "silently — install beadloom BEFORE the Pytest step"
    )
    assert _INDEX.exists(), (
        f"no index at {_INDEX}, so the real-binary tests skip as 'repo not indexed' — "
        "run beadloom reindex BEFORE the Pytest step"
    )

    pinned = os.environ.get(_PINNED_VERSION_ENV, "")
    assert pinned, f"the job declares no {_PINNED_VERSION_ENV}: nothing to check the build against"

    proc = subprocess.run(  # noqa: S603 — the binary PATH resolved above, fixed argv
        [binary, "--version"],
        capture_output=True,
        text=True,
        timeout=_VERSION_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    words = proc.stdout.split()
    reported = words[-1] if words else ""
    assert reported == pinned, (
        f"beadloom on PATH reports {reported!r} but the job pins {pinned!r}: the real-binary "
        "tests would check another build"
    )
