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


class _ListingCommand:
    """A runner that returns a canned ``worktree list --porcelain`` listing."""

    def __init__(self, *, listing: str) -> None:
        self.calls: list[list[str]] = []
        self._listing = listing

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        if "list" in argv:
            return self._listing
        return ""


class _BranchAwareCommand:
    """A runner that also answers ``git branch --list <branch>`` from a canned set."""

    def __init__(self, *, listing: str, existing_branches: tuple[str, ...]) -> None:
        self.calls: list[list[str]] = []
        self._listing = listing
        self._existing = existing_branches

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        if "list" in argv and "worktree" in argv:
            return self._listing
        if "branch" in argv:
            branch = argv[-1]
            return f"  {branch}\n" if branch in self._existing else ""
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


# --- ensure (BOB-087.D1): idempotent PERSISTENT (long-lived, named) worktree ---


async def test_ensure_creates_the_worktree_when_not_yet_registered(
    tmp_path: Path,
) -> None:
    runner = _ListingCommand(listing="")  # no worktree registered yet
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")

    path = await wt.ensure("bob/epic-x")

    assert Path(path).parent == tmp_path
    # It lists first, checks whether the branch already exists, then adds it fresh.
    assert runner.calls[0] == ["my-git", "worktree", "list", "--porcelain"]
    assert runner.calls[1] == ["my-git", "branch", "--list", "bob/epic-x"]
    assert runner.calls[2] == ["my-git", "worktree", "add", path, "-b", "bob/epic-x"]


async def test_ensure_reuses_an_already_registered_worktree_without_adding(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "epic-x")
    listing = f"worktree {path}\nHEAD abc123\nbranch refs/heads/bob/epic-x\n"
    runner = _ListingCommand(listing=listing)
    wt = GitWorktree(tmp_path, runner=runner)

    returned = await wt.ensure("bob/epic-x")

    # Persistence: an existing long-lived worktree is REUSED — never re-added, never
    # removed — so work accumulates across sessions.
    assert returned == path
    verbs = [argv[2] for argv in runner.calls]  # argv = [git, worktree, <verb>, ...]
    assert verbs == ["list"]  # only listed; NO add, NO remove


async def test_ensure_reuses_a_registered_worktree_with_a_RELATIVE_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 BOB-087.D5b (B1): in production ``coder.worktree_root`` defaults to the RELATIVE
    # ``.worktrees``, while ``git worktree list --porcelain`` always prints ABSOLUTE paths.
    # Comparing the two verbatim never matched, so the reuse branch was dead and every
    # later ensure re-ran ``worktree add -b`` → «fatal: a branch already exists».
    monkeypatch.chdir(tmp_path)
    absolute = str((tmp_path / ".worktrees" / "epic-x").resolve())
    listing = f"worktree {absolute}\nHEAD abc123\nbranch refs/heads/bob/epic-x\n"
    runner = _ListingCommand(listing=listing)
    wt = GitWorktree(".worktrees", runner=runner)

    returned = await wt.ensure("bob/epic-x")

    assert returned == absolute
    verbs = [argv[2] for argv in runner.calls]
    assert verbs == ["list"]  # REUSED: no add (and never a remove)


async def test_ensure_reuses_a_worktree_listed_through_a_symlinked_root(
    tmp_path: Path,
) -> None:
    # The same normalisation must survive a symlinked root (macOS ``/tmp`` → ``/private/tmp``
    # is exactly this case): porcelain prints the REAL path, the config carries the link.
    real_root = tmp_path / "real"
    (real_root / "epic-x").mkdir(parents=True)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root)
    listing = f"worktree {real_root / 'epic-x'}\nbranch refs/heads/bob/epic-x\n"
    runner = _ListingCommand(listing=listing)
    wt = GitWorktree(linked_root, runner=runner)

    await wt.ensure("bob/epic-x")

    assert [argv[2] for argv in runner.calls] == ["list"]


async def test_ensure_checks_out_an_EXISTING_branch_instead_of_recreating_it(
    tmp_path: Path,
) -> None:
    # 🔴 The other half of B1: if the tree is gone but the branch survives (a manually
    # deleted worktree, a pruned registration), ``add -b`` dies with «a branch named …
    # already exists». ``ensure`` promises idempotency, so it checks the branch out.
    runner = _BranchAwareCommand(listing="", existing_branches=("bob/epic-x",))
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")

    path = await wt.ensure("bob/epic-x")

    assert runner.calls[-1] == ["my-git", "worktree", "add", path, "bob/epic-x"]
    assert "-b" not in runner.calls[-1]


async def test_ensure_creates_a_fresh_branch_when_none_exists(tmp_path: Path) -> None:
    runner = _BranchAwareCommand(listing="", existing_branches=())
    wt = GitWorktree(tmp_path, runner=runner, git_bin="my-git")

    path = await wt.ensure("bob/epic-x")

    assert runner.calls[-1] == ["my-git", "worktree", "add", path, "-b", "bob/epic-x"]


@pytest.mark.parametrize(
    "branch",
    ["main", "BOB/Caps", "bob/../etc", "bob/has space", "feature/x", "bob/"],
)
async def test_ensure_rejects_a_branch_outside_the_bob_slug_form(
    tmp_path: Path, branch: str
) -> None:
    runner = _ListingCommand(listing="")
    wt = GitWorktree(tmp_path, runner=runner)

    with pytest.raises(WorktreeError):
        await wt.ensure(branch)

    assert runner.calls == []


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
