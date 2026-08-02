# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""GitWorktree — isolated git worktree for a gated coding session (BOB-039 .2).

The infrastructure adapter realising :class:`bob.coding.ports.Worktree`. It runs git
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

from bob.coding.adapters._branch import is_safe_branch
from bob.coding.adapters._exec import (
    DEFAULT_TIMEOUT_S,
    CommandRunner,
    ExecRunner,
)

__all__ = ["GitWorktree", "WorktreeError"]

_WORKTREE_LINE_PREFIX = "worktree "


def _registered_worktrees(porcelain: str) -> set[Path]:
    """Parse the paths out of ``git worktree list --porcelain`` as RESOLVED paths.

    Each worktree stanza opens with a ``worktree <abs-path>`` line; the set of those
    paths is what :meth:`GitWorktree.ensure` checks to decide REUSE vs add. Non-worktree
    lines (``HEAD``/``branch``/blank) are ignored.

    🔴 Paths are normalised with :meth:`Path.resolve` (BOB-087.D5b): porcelain always
    prints ABSOLUTE, symlink-resolved paths, while ``coder.worktree_root`` is RELATIVE by
    default (``.worktrees``). Comparing the two verbatim never matched, so the reuse
    branch was dead in production; both sides are resolved before the comparison now.
    """
    return {
        Path(line[len(_WORKTREE_LINE_PREFIX) :].strip()).resolve()
        for line in porcelain.splitlines()
        if line.startswith(_WORKTREE_LINE_PREFIX)
    }


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

    async def ensure(self, branch: str) -> str:
        """Ensure a PERSISTENT (long-lived, named) worktree on ``branch`` exists; reuse it.

        BOB-087.D1: a durable ``bob/epic-<slug>`` workspace (see
        :func:`bob.coding.naming.workspace_branch`) whose work ACCUMULATES across
        sessions — unlike :meth:`create`'s per-task ephemeral worktree. Idempotent and
        fixed-form (shell-free):

        * ``git worktree list --porcelain`` — if the target path is ALREADY registered,
          return it as-is (REUSE — never re-added, and this adapter never removes it),
          so a resumed session lands back in the same accumulated tree.
        * otherwise ``git worktree add <path> <branch>`` on the EXISTING branch, or
          ``git worktree add <path> -b <branch>`` when the branch is new.

        🔴 Both halves of the idempotency are load-bearing (BOB-087.D5b): the registered
        path is compared on RESOLVED paths (porcelain prints absolute, symlink-resolved
        paths; ``worktree_root`` is relative by default), and an already-existing branch
        is CHECKED OUT rather than re-created — otherwise the second raise of the same
        workspace died with «fatal: a branch named … already exists» and the promise
        «work accumulates across sessions» was broken from the second session on.

        The branch is validated to the ``bob/<slug>`` shape first (path-injection is
        refused before git runs), and the path is always a child of ``worktree_root``.
        🔴 Isolation is unchanged: a persistent worktree is still a worktree, NOT the
        main tree — integration stays via a PR (main is never touched here).
        """
        if not is_safe_branch(branch):
            raise WorktreeError(
                f"branch {branch!r} is not a safe bob/<slug> coding branch"
            )
        slug = branch.split("/", 1)[1]
        path = (self._worktree_root / slug).resolve()
        listing = await self._runner(
            [self._git_bin, "worktree", "list", "--porcelain"],
            timeout=self._timeout,
        )
        if path in _registered_worktrees(listing):
            return str(path)
        add_argv = [self._git_bin, "worktree", "add", str(path)]
        if await self._branch_exists(branch):
            add_argv.append(branch)  # check the accumulated branch out — never ``-b``
        else:
            add_argv += ["-b", branch]
        await self._runner(add_argv, timeout=self._timeout)
        return str(path)

    async def _branch_exists(self, branch: str) -> bool:
        """Whether ``branch`` already exists locally (``git branch --list <branch>``).

        ``--list`` is chosen deliberately over ``rev-parse --verify``: it exits 0 whether
        or not the branch is there (empty stdout = absent), so a plain «no such branch»
        never surfaces as a :class:`CommandError` we would have to swallow — and a
        swallowed error is exactly how a real git failure would get misread as «absent».
        """
        listed = await self._runner(
            [self._git_bin, "branch", "--list", branch], timeout=self._timeout
        )
        return bool(listed.strip())

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        """Stage, commit and push the worktree's changes to its ``bob/<slug>`` branch.

        Bob's DETERMINISTIC integration step (BOB-040): after ``claude`` applies the
        approved plan inside the isolated worktree it does NOT commit (``acceptEdits``
        auto-accepts file edits only, never git), so Bob commits + pushes the feature
        branch himself before a PR can be opened. Runs, all fixed-form and shell-free:

        * ``git -C <path> add -A`` — stage every change in the worktree.
        * ``git -C <path> status --porcelain`` — if it is EMPTY, ``claude`` made no
          changes: return ``False`` (the honest "nothing to commit" signal) WITHOUT
          committing — never an empty commit.
        * ``git -C <path> commit -m <message>`` then
          ``git -C <path> push -u origin <branch>`` — only on a real change.

        🔴 ``branch`` MUST be the validated ``bob/<slug>`` feature branch
        (:func:`is_safe_branch`); any other branch is refused BEFORE git runs, so there
        is physically no code path that can push ``main``. Returns ``True`` when a real
        commit was pushed, ``False`` when there was nothing to commit; a genuine git
        failure surfaces as the runner's :class:`CommandError`.
        """
        if not is_safe_branch(branch):
            raise WorktreeError(
                f"refusing to push branch {branch!r}: not a safe bob/<slug> branch"
            )
        await self._runner(
            [self._git_bin, "-C", path, "add", "-A"], timeout=self._timeout
        )
        status = await self._runner(
            [self._git_bin, "-C", path, "status", "--porcelain"], timeout=self._timeout
        )
        if not status.strip():
            return False  # claude applied no changes — fail honestly, no empty commit
        await self._runner(
            [self._git_bin, "-C", path, "commit", "-m", message], timeout=self._timeout
        )
        await self._runner(
            [self._git_bin, "-C", path, "push", "-u", "origin", branch],
            timeout=self._timeout,
        )
        return True

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
