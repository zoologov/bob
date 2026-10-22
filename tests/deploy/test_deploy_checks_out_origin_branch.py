# Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
# SPDX-License-Identifier: BUSL-1.1
"""BOB-125: a deploy by BRANCH name lands the branch's tip from origin, not the stale local branch.

Runs the workflow's own remote script against a REAL git clone whose local ``main`` is one
commit behind ``origin/main`` (exactly the VPS state of 2026-10-22, when two deploys shipped
old code). Only ``git`` is real here; the other tools stay the harness stubs.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.deploy.conftest import STUBS

from .test_deploy_workflow import _deploy

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which("git") or "git"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 — real git on a throwaway repo
        [_GIT, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _stale_clone(tmp_path: Path) -> tuple[Path, str, str]:
    """A bare origin at commit B; a clone whose local main sits at commit A (behind)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@example")
    _git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("A\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-q", "-m", "A")
    _git(work, "push", "-q", "origin", "main")
    commit_a = _git(work, "rev-parse", "HEAD")
    # the server's clone is taken at A …
    home = tmp_path / "opt-bob"
    _git(tmp_path, "clone", "-q", str(origin), str(home))
    # … and origin moves on to B
    (work / "b.txt").write_text("B\n", encoding="utf-8")
    _git(work, "add", "b.txt")
    _git(work, "commit", "-q", "-m", "B")
    _git(work, "push", "-q", "origin", "main")
    commit_b = _git(work, "rev-parse", "HEAD")
    return home, commit_a, commit_b


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_a_deploy_by_branch_name_lands_the_origin_tip_not_the_stale_local_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, commit_a, commit_b = _stale_clone(tmp_path)
    assert _git(home, "rev-parse", "HEAD") == commit_a
    real_git = shutil.which("git")
    assert real_git is not None
    monkeypatch.setitem(STUBS, "git", f'exec "{real_git}" "$@"\n')

    run = _deploy(tmp_path, stub_env={"DEPLOY_REF": "main"})

    assert run.returncode == 0, run.output
    assert _git(home, "rev-parse", "HEAD") == commit_b, (
        "деплой по имени ветки оставил локальную ветку на старом коммите:\n" + run.output
    )
    assert _git(home, "rev-parse", "--abbrev-ref", "HEAD") == "main"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_a_deploy_by_tag_still_checks_out_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, commit_a, _commit_b = _stale_clone(tmp_path)
    _git(home, "tag", "v9.9.9", commit_a)
    real_git = shutil.which("git")
    assert real_git is not None
    monkeypatch.setitem(STUBS, "git", f'exec "{real_git}" "$@"\n')

    run = _deploy(tmp_path, stub_env={"DEPLOY_REF": "v9.9.9"})

    assert run.returncode == 0, run.output
    assert _git(home, "rev-parse", "HEAD") == commit_a
