# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""GitWorktree — isolated git worktree for a gated coding session (BOB-039 .2).

The infrastructure adapter realising :class:`bob.domain.ports.Worktree`. It runs git
as FIXED-form, shell-free invocations (no metacharacter injection):

* :meth:`create` → ``git worktree add <path> -b <branch>`` on a NEW branch, returning
  the worktree path (always a child of the configured ``worktree_root``). The branch
  is validated to the ``bob/<slug>`` shape first; anything else is refused before git
  runs. The fresh worktree contains ONLY tracked files, so Bob's gitignored private
  data (``data/soul/``, ``bob.db*``, ``.env*``, ``config/*``) is ABSENT — that
  absence IS the privacy isolation, and this adapter reads none of it.
* :meth:`remove` → ``git worktree remove --force <path>`` (the use-case calls it in a
  ``finally`` so an aborted session still cleans up). The path is validated to be a
  child of ``worktree_root`` (a symlink-resolved containment check) before git runs.

The subprocess boundary is injected (``runner``) so tests drive the argv with a fake
and never spawn real git.
"""

from __future__ import annotations

import os
from pathlib import Path

from bob.infrastructure.coding._branch import is_safe_branch
from bob.infrastructure.coding._exec import (
    DEFAULT_TIMEOUT_S,
    CommandRunner,
    ExecRunner,
)

__all__ = ["GitWorktree", "WorktreeError"]


class WorktreeError(Exception):
    """A worktree operation was refused (unsafe branch / path) or git failed."""


class GitWorktree:
    """Create / remove an isolated git worktree via fixed-form, shell-free git."""

    def __init__(
        self,
        worktree_root: Path | str,
        *,
        runner: CommandRunner | None = None,
        git_bin: str = "git",
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._worktree_root = Path(worktree_root)
        self._runner: CommandRunner = runner or ExecRunner()
        self._git_bin = git_bin
        self._timeout = timeout

    async def create(self, branch: str) -> str:
        """Add an isolated worktree on ``branch`` and return its filesystem path."""
        if not is_safe_branch(branch):
            raise WorktreeError(
                f"branch {branch!r} is not a safe bob/<slug> coding branch"
            )
        slug = branch.split("/", 1)[1]
        path = self._worktree_root / slug
        await self._runner(
            [self._git_bin, "worktree", "add", str(path), "-b", branch],
            timeout=self._timeout,
        )
        return str(path)

    async def remove(self, path: str) -> None:
        """Remove the worktree at ``path`` (refused unless it is under the root)."""
        if not self._is_under_root(path):
            raise WorktreeError(
                f"worktree path {path!r} is not under the configured worktree root"
            )
        await self._runner(
            [self._git_bin, "worktree", "remove", "--force", path],
            timeout=self._timeout,
        )

    def _is_under_root(self, path: str) -> bool:
        """Whether ``path`` resolves to a STRICT child of the worktree root.

        Containment is computed on symlink-resolved real paths so neither the root
        itself nor a path escaping it (``/etc/passwd``, a ``..`` traversal, a symlink
        out of the root) is ever handed to ``git worktree remove``.
        """
        if not path:
            return False
        real_target = Path(os.path.realpath(path))
        real_root = Path(os.path.realpath(self._worktree_root))
        return real_root in real_target.parents
