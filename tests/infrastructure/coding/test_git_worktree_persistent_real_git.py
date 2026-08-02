# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-GIT acceptance: the PERSISTENT workspace is genuinely idempotent (BOB-087.D5b).

The gap the fakes could not cover — and did not (security-review B1). The persistent
workspace promise is «work ACCUMULATES across sessions», i.e.
:meth:`~bob.coding.adapters.git_worktree.GitWorktree.ensure` must be callable again and
again on the SAME branch. The unit fake modelled that contract; the adapter did not:

* ``git worktree list --porcelain`` prints ABSOLUTE, symlink-resolved paths, while
  ``coder.worktree_root`` defaults to the RELATIVE ``.worktrees`` — so the reuse check
  never matched and every later ensure re-ran ``worktree add -b``, which dies with
  «fatal: a branch named 'bob/epic-x' already exists»;
* the unit test that «proved» reuse passed an ABSOLUTE ``tmp_path`` root, masking it.

So this file drives the PRODUCTION adapter over the PRODUCTION :class:`ExecRunner`
against REAL git on a THROW-AWAY repo, with the RELATIVE root production actually uses
(lesson BOB-084: a fake does not model the real transport). It asserts what the owner
would notice: the second raise succeeds, lands in the same tree, and the work written
during the first session is still there.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.coding.adapters._exec import ExecRunner
from bob.coding.adapters.git_worktree import GitWorktree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

_WORKSPACE_BRANCH = "bob/epic-bob-087"
#: The production default of ``coder.worktree_root`` — RELATIVE, as in ``config/bob.yaml``.
_RELATIVE_ROOT = ".worktrees"


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
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throw-away repo, with the process cwd inside it (as the live bot runs)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("public readme\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial tracked tree")
    # The adapter resolves a RELATIVE worktree root against the process cwd, exactly as
    # the live bot does (it runs from the repo root) — so the test moves there too.
    monkeypatch.chdir(root)
    return root


async def test_second_ensure_reuses_the_workspace_and_keeps_the_accumulated_work(
    repo: Path,
) -> None:
    adapter = GitWorktree(_RELATIVE_ROOT, runner=ExecRunner())

    first = await adapter.ensure(_WORKSPACE_BRANCH)
    # A session's accumulated work: an uncommitted edit left in the tree.
    (Path(first) / "work-in-progress.txt").write_text("наработано\n", encoding="utf-8")

    # 🔴 The second raise must not die on «a branch named … already exists».
    second = await adapter.ensure(_WORKSPACE_BRANCH)

    assert Path(second).resolve() == Path(first).resolve()
    assert (Path(second) / "work-in-progress.txt").read_text(encoding="utf-8") == (
        "наработано\n"
    )
    # Exactly ONE worktree was ever registered for the workspace.
    listing = _git(repo, "worktree", "list", "--porcelain")
    assert listing.count(str(Path(first).resolve())) == 1


async def test_ensure_recovers_when_the_tree_is_gone_but_the_branch_remains(
    repo: Path,
) -> None:
    # The branch outlives its registration (a manually deleted tree + ``worktree prune``).
    adapter = GitWorktree(_RELATIVE_ROOT, runner=ExecRunner())
    first = await adapter.ensure(_WORKSPACE_BRANCH)
    shutil.rmtree(first)
    _git(repo, "worktree", "prune")

    revived = await adapter.ensure(_WORKSPACE_BRANCH)

    assert Path(revived).is_dir()
    head = _git(Path(revived), "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert head == _WORKSPACE_BRANCH  # checked the EXISTING branch out, never re-created


async def test_ensure_creates_the_workspace_on_a_fresh_branch_the_first_time(
    repo: Path,
) -> None:
    adapter = GitWorktree(_RELATIVE_ROOT, runner=ExecRunner())

    path = await adapter.ensure(_WORKSPACE_BRANCH)

    assert Path(path).is_dir()
    assert Path(path).parent == (repo / _RELATIVE_ROOT).resolve()
    assert (Path(path) / "README.md").is_file()  # a real checkout of the tracked tree
