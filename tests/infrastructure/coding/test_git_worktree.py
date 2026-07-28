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

from bob.coding.adapters.git_worktree import GitWorktree, WorktreeError
from bob.coding.ports import Worktree


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


class _ScriptedCommand:
    """A runner that returns a per-subcommand canned stdout (keyed by the git verb)."""

    def __init__(self, *, status_out: str) -> None:
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []
        self._status_out = status_out

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.calls.append(list(argv))
        self.timeouts.append(timeout)
        # ``git -C <path> status --porcelain`` is the only call whose stdout matters.
        if "status" in argv:
            return self._status_out
        return ""


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


# --- commit_and_push (BOB-040 .1): deterministic commit+push of the feature branch ---


async def test_commit_and_push_builds_add_commit_push_argv(tmp_path: Path) -> None:
    runner = _ScriptedCommand(status_out=" M foo.py\n")  # something to commit
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")
    target = str(tmp_path / "bob-fix")

    committed = await wt.commit_and_push(target, "bob/fix", "[BOB] do the thing")

    assert committed is True
    assert runner.calls == [
        ["my-git", "-C", target, "add", "-A"],
        ["my-git", "-C", target, "status", "--porcelain"],
        ["my-git", "-C", target, "commit", "-m", "[BOB] do the thing"],
        ["my-git", "-C", target, "push", "-u", "origin", "bob/fix"],
    ]


async def test_commit_and_push_passes_the_configured_timeout(tmp_path: Path) -> None:
    runner = _ScriptedCommand(status_out=" M foo.py\n")
    wt = GitWorktree(tmp_path, runner=runner, timeout=7.0)

    await wt.commit_and_push(str(tmp_path / "bob-x"), "bob/x", "msg")

    # Every git call carried the adapter's configured timeout.
    assert runner.timeouts
    assert all(t == 7.0 for t in runner.timeouts)


async def test_commit_and_push_nothing_to_commit_returns_false_and_never_commits(
    tmp_path: Path,
) -> None:
    runner = _ScriptedCommand(status_out="")  # clean tree → nothing to commit
    wt = GitWorktree(tmp_path, runner=runner)

    committed = await wt.commit_and_push(str(tmp_path / "bob-x"), "bob/x", "msg")

    assert committed is False
    verbs = [argv[3] for argv in runner.calls]  # argv = [git, -C, path, <verb>, ...]
    # add + status ran, but NEVER commit and NEVER push (no empty commit, no push).
    assert verbs == ["add", "status"]


@pytest.mark.parametrize(
    "branch",
    ["main", "BOB/x", "bob/../etc", "feature/x", "bob/", "origin/main", "bob/UP"],
)
async def test_commit_and_push_refuses_a_non_bob_branch_never_pushing(
    tmp_path: Path, branch: str
) -> None:
    runner = _ScriptedCommand(status_out=" M foo.py\n")
    wt = GitWorktree(tmp_path, runner=runner)

    with pytest.raises(WorktreeError):
        await wt.commit_and_push(str(tmp_path / "x"), branch, "msg")

    # A refused branch never reaches git — there is no path that can push main.
    assert runner.calls == []
