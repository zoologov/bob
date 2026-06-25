# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 PRIVACY/ISOLATION acceptance — a coding worktree carries NO personal data.

BOB-039 US-5. This is the *real* isolation guarantee, so it is exercised with REAL
``git`` on a THROW-AWAY temporary repo (never the live repo). We build a tiny repo
whose private files mirror Bob's own — ``data/bob.db``, ``.env``, ``config/*`` and
``data/soul/*`` — and gitignore them (exactly as the live repo does). Then we drive
:class:`~bob.infrastructure.coding.git_worktree.GitWorktree` (the production adapter,
unmodified) and assert the fresh worktree checkout contains ONLY the tracked files —
the gitignored secrets are ABSENT. That absence IS the privacy isolation: Claude Code
runs with the worktree as its cwd and never sees the soul / db / env / config.

The adapter deliberately builds a fixed ``git worktree add <path> -b <branch>`` argv
and does NOT manage cwd (the live bot process runs from the repo root), so the test
injects a runner that runs the very same argv with ``cwd`` set to the temp repo — the
git mechanics (a clean checkout of the committed tree) are genuinely under test.

Skips with a clear reason when ``git`` is unavailable.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from bob.infrastructure.coding.git_worktree import GitWorktree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="real git is not available on this host"
)

# Bob's private, gitignored data — none of it may ever reach a coding worktree.
_SECRET_FILES = (
    "data/bob.db",
    "data/bob.db-wal",
    ".env",
    "config/secrets.yml",
    "data/soul/identity.json",
)
# The tracked, shareable code that the worktree SHOULD carry.
_TRACKED_FILES = ("README.md", "src/app.py")


class _RepoRunner:
    """Run the adapter's fixed git argv with ``cwd`` pinned to the temp repo.

    The adapter builds a shell-free, fixed-form argv; in production the bot's cwd is
    the repo root, so the only thing the test supplies is that cwd — the real git
    worktree checkout is what we are validating.
    """

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.calls.append(list(argv))
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self._repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:  # pragma: no cover - surfaced only on a real git failure
            raise RuntimeError(err.decode("utf-8", errors="replace"))
        return out.decode("utf-8", errors="replace")


def _git(repo: Path, *args: str) -> None:
    """Run a one-shot git command in ``repo`` (test setup only)."""
    subprocess.run(  # noqa: S603 - fixed argv, test-local temp repo
        ["git", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo_with_secrets(tmp_path: Path) -> Path:
    """A throw-away git repo: tracked code committed, private data gitignored."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    # Tracked, shareable files.
    (repo / "README.md").write_text("public readme\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")

    # The gitignore mirrors the live repo's private surface.
    (repo / ".gitignore").write_text(
        "data/\n.env\nconfig/\n*.db\n*.db-wal\n", encoding="utf-8"
    )

    # The private data that MUST NOT leak into a worktree.
    for rel in _SECRET_FILES:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("TOP SECRET\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial tracked tree")
    return repo


async def test_worktree_checkout_excludes_all_gitignored_private_data(
    repo_with_secrets: Path, tmp_path: Path
) -> None:
    # Arrange — the adapter under test, with a cwd-pinned real-git runner.
    worktree_root = tmp_path / "worktrees"
    runner = _RepoRunner(repo_with_secrets)
    adapter = GitWorktree(worktree_root, runner=runner)

    # Act — create the isolated worktree (real `git worktree add`).
    path = await adapter.create("bob/isolation-check")
    checkout = Path(path)

    # Assert — the tracked code is present...
    assert checkout.is_dir()
    for rel in _TRACKED_FILES:
        assert (checkout / rel).is_file(), f"tracked file {rel} should be checked out"

    # ...and EVERY private, gitignored file is ABSENT (the isolation guarantee).
    for rel in _SECRET_FILES:
        assert not (checkout / rel).exists(), f"PRIVACY LEAK: {rel} reached the worktree"
    assert not (checkout / "data").exists()
    assert not (checkout / "config").exists()
    assert not (checkout / ".env").exists()


async def test_worktree_lives_under_root_and_remove_cleans_it_up(
    repo_with_secrets: Path, tmp_path: Path
) -> None:
    # Arrange
    worktree_root = tmp_path / "worktrees"
    runner = _RepoRunner(repo_with_secrets)
    adapter = GitWorktree(worktree_root, runner=runner)

    # Act — create then remove via the real adapter + real git.
    path = await adapter.create("bob/cleanup-check")
    assert Path(path).is_dir()
    assert worktree_root in Path(path).parents  # contained under the configured root

    await adapter.remove(path)

    # Assert — the worktree directory is gone (no leak on the live path either).
    assert not Path(path).exists()
