# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for GitWorktree (BOB-039 .2).

The adapter realises :class:`bob.domain.ports.Worktree` by running git as FIXED-form,
shell-free invocations (``git worktree add <path> -b <branch>`` / ``git worktree
remove --force <path>``). The subprocess boundary is injected as a fake here so the
tests are deterministic and NEVER spawn real git: the fake records the argv it is
handed. Isolation is structural — a fresh worktree contains only TRACKED files, so
Bob's gitignored private data (``data/soul/``, ``bob.db*``, ``.env*``, ``config/*``)
is absent — but the adapter's job is only to build the safe argv, which is what we
assert. The dynamic slots (branch shape, removal path) are validated; anything off
the fixed form is refused before git runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.domain.ports import Worktree
from bob.infrastructure.coding.git_worktree import GitWorktree, WorktreeError


class _FakeCommand:
    """A scripted command runner: records argv + timeout, returns canned stdout."""

    def __init__(self, *, stdout: str = "", raises: BaseException | None = None) -> None:
        self.calls: list[list[str]] = []
        self.seen_timeout: float = 0.0
        self._stdout = stdout
        self._raises = raises

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.seen_timeout = timeout
        self.calls.append(list(argv))
        if self._raises is not None:
            raise self._raises
        return self._stdout


async def test_create_builds_the_fixed_worktree_add_argv(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")

    path = await wt.create("bob/fix-typo")

    argv = runner.calls[0]
    assert argv == [
        "my-git",
        "worktree",
        "add",
        path,
        "-b",
        "bob/fix-typo",
    ]
    # The worktree path lives under the configured root.
    assert Path(path).parent == tmp_path


async def test_create_passes_the_configured_timeout(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner, timeout=42.0)

    await wt.create("bob/work")

    assert runner.seen_timeout == 42.0


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "BOB/Caps",
        "bob/../etc",
        "bob/has space",
        "feature/x",
        "bob/",
        "bob/UPPER",
        "../bob/x",
    ],
)
async def test_create_rejects_a_branch_outside_the_bob_slug_form(
    tmp_path: Path, branch: str
) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner)

    with pytest.raises(WorktreeError):
        await wt.create(branch)

    # A rejected branch never reaches git.
    assert runner.calls == []


async def test_remove_builds_the_fixed_force_remove_argv(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")
    target = str(tmp_path / "bob-work")

    await wt.remove(target)

    assert runner.calls[0] == ["my-git", "worktree", "remove", "--force", target]


async def test_remove_rejects_a_path_outside_the_worktree_root(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner)

    with pytest.raises(WorktreeError):
        await wt.remove("/etc/passwd")

    assert runner.calls == []


async def test_remove_rejects_the_root_itself(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner)

    with pytest.raises(WorktreeError):
        await wt.remove(str(tmp_path))

    assert runner.calls == []


async def test_create_then_remove_round_trips_under_root(tmp_path: Path) -> None:
    runner = _FakeCommand()
    wt = GitWorktree(tmp_path, runner=runner)

    path = await wt.create("bob/round-trip")
    await wt.remove(path)

    # Only ever the two fixed worktree forms — never another git subcommand.
    assert [call[1] for call in runner.calls] == ["worktree", "worktree"]
    assert runner.calls[0][2] == "add"
    assert runner.calls[1][2] == "remove"


def test_git_worktree_satisfies_the_worktree_port(tmp_path: Path) -> None:
    assert isinstance(GitWorktree(tmp_path), Worktree)
