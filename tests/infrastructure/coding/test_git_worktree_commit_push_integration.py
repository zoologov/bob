# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance for the deterministic commit+push (BOB-040 .2).

This is the gap the fakes could not cover: the *actual* git mechanics of
:meth:`~bob.coding.adapters.git_worktree.GitWorktree.commit_and_push`. The
original T3.B bug was that ``claude`` (acceptEdits) applies file edits but never runs
git, so the ``bob/<slug>`` branch had NO commits and ``gh pr create`` failed with "No
commits between main and bob/<slug>". Bob now commits + pushes the feature branch
deterministically — and the only way to be sure is to drive REAL git on a THROW-AWAY
temp repo with a LOCAL BARE REMOTE (so ``push`` works with no network / no real
origin), NEVER the live repo.

We build a tiny repo on ``main`` wired to a bare ``origin``, add a real ``bob/<slug>``
worktree, write a file in it (simulating a claude edit), call the PRODUCTION adapter's
``commit_and_push`` through the PRODUCTION :class:`ExecRunner` (the adapter's git is
all ``-C <path>``, so no cwd juggling), and assert:

* the commit exists on the ``bob/<slug>`` branch,
* the branch was pushed to the bare remote (a subsequent ``gh pr create`` has a target),
* ``git log main..bob/<slug>`` is NON-empty — so the PR diff is non-empty and the
  original "No commits between main and bob/<slug>" failure cannot recur,
* the empty case (no file change) returns ``False`` and creates NO commit.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_worktree import GitWorktree, WorktreeError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)


def _git(cwd: Path, *args: str) -> str:
    """Run a one-shot git command in ``cwd`` (test setup / assertions only)."""
    result = subprocess.run(  # noqa: S603 - fixed argv, test-local temp repo
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A throw-away repo on ``main`` wired to a LOCAL BARE ``origin`` remote.

    Returns ``(work_repo, bare_remote)``. The bare remote already carries ``main`` so a
    pushed ``bob/<slug>`` branch is genuinely a feature branch ahead of the trunk.
    """
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", str(bare))

    (work / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "initial tree on main")
    _git(work, "push", "-u", "origin", "main")
    return work, bare


async def test_commit_and_push_lands_a_real_commit_on_the_feature_branch(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    # Arrange — a real bob/<slug> worktree + a claude-style edit inside it.
    work, bare = repo_with_remote
    wt_path = tmp_path / "wt"
    _git(work, "worktree", "add", str(wt_path), "-b", "bob/add-feature")
    (wt_path / "feature.py").write_text("print('new feature')\n", encoding="utf-8")
    adapter = GitWorktree(tmp_path / "roots", runner=ExecRunner())

    # Act — the PRODUCTION adapter commits + pushes via REAL git.
    committed = await adapter.commit_and_push(
        str(wt_path), "bob/add-feature", "[bob] add feature"
    )

    # Assert — a real commit was reported and exists on the branch with our message.
    assert committed is True
    subjects = _git(work, "log", "bob/add-feature", "--format=%s").splitlines()
    assert subjects[0] == "[bob] add feature"
    # 🔴 git log main..bob/<slug> is NON-empty → the PR diff exists; the original
    # "No commits between main and bob/add-feature" failure cannot recur.
    ahead = _git(work, "log", "main..bob/add-feature", "--format=%H").splitlines()
    assert len(ahead) == 1
    # The branch was pushed to the bare remote → gh pr create has a target ref.
    remote_subject = _git(bare, "log", "-1", "bob/add-feature", "--format=%s").strip()
    assert remote_subject == "[bob] add feature"
    # The committed file is part of that commit's tree.
    files = _git(work, "show", "--name-only", "--format=", "bob/add-feature")
    assert "feature.py" in files


async def test_commit_and_push_no_change_reports_nothing_to_commit_no_commit(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    # Arrange — a real bob/<slug> worktree with NO edit (claude changed nothing).
    work, bare = repo_with_remote
    wt_path = tmp_path / "wt-empty"
    _git(work, "worktree", "add", str(wt_path), "-b", "bob/no-change")
    head_before = _git(work, "rev-parse", "bob/no-change").strip()
    adapter = GitWorktree(tmp_path / "roots", runner=ExecRunner())

    # Act — nothing was edited in the worktree.
    committed = await adapter.commit_and_push(
        str(wt_path), "bob/no-change", "[bob] should not happen"
    )

    # Assert — honest "nothing to commit": no empty commit, branch HEAD unchanged.
    assert committed is False
    head_after = _git(work, "rev-parse", "bob/no-change").strip()
    assert head_after == head_before
    # git log main..bob/<slug> is empty → no phantom PR diff.
    ahead = _git(work, "log", "main..bob/no-change", "--format=%H").strip()
    assert ahead == ""
    # The branch was never pushed — the bare remote has no such ref (empty listing).
    assert _git(bare, "branch", "--list", "bob/no-change").strip() == ""


async def test_commit_and_push_refuses_main_against_real_git_remote_untouched(
    repo_with_remote: tuple[Path, Path], tmp_path: Path
) -> None:
    # Arrange — a real worktree with a staged change, but we ask to push `main`.
    work, bare = repo_with_remote
    wt_path = tmp_path / "wt-main"
    _git(work, "worktree", "add", str(wt_path), "-b", "bob/safe-slug")
    (wt_path / "evil.py").write_text("print('do not land on main')\n", encoding="utf-8")
    remote_main_before = _git(bare, "rev-parse", "main").strip()
    adapter = GitWorktree(tmp_path / "roots", runner=ExecRunner())

    # Act / Assert — 🔴 the adapter refuses `main` BEFORE any git runs; no push path.
    with pytest.raises(WorktreeError):
        await adapter.commit_and_push(str(wt_path), "main", "[bob] never main")

    # The bare remote's `main` is byte-for-byte untouched — nothing was pushed to it.
    assert _git(bare, "rev-parse", "main").strip() == remote_main_before
