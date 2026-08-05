# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Coding-session infrastructure adapters (BOB-039 .2, gated «Bob runs Claude Code»).

Realise the gated coding seam's outward ports via FIXED-form, shell-free subprocess
adapters (the BOB-031/038 safety pattern — ``create_subprocess_exec`` only, every
dynamic slot validated):

* :class:`GitWorktree` (:class:`~bob.coding.ports.Worktree`) — an isolated git
  worktree on a ``bob/<slug>`` branch; only tracked files are present, so Bob's
  gitignored private data never reaches Claude Code.
* :class:`GitClone` (the same ports, BOB-089.A) — the same workplace as a SEPARATE
  CLONE with its own ``.git``, so the main repo's refs/remotes are not shared and
  ``git update-ref refs/heads/main`` cannot reach the owner's trunk. Substituted for
  :class:`GitWorktree` in the composition root under ``coder.isolated_clone``.
* :class:`SubprocessClaudeRunner` (:class:`~bob.coding.ports.ClaudeCodeRunner`) — runs
  the local ``claude`` CLI headless with ``--output-format stream-json`` and a fixed
  ``--permission-mode`` allowlist, streaming NDJSON events.
* :class:`GhPullRequestOpener` (:class:`~bob.coding.ports.PullRequestOpener`) — opens a
  PR via ``gh pr create`` only; there is no integrate-to-trunk path (the owner lands it).
"""

from bob.coding.adapters.claude_runner import (
    ClaudeRunError,
    SubprocessClaudeRunner,
)
from bob.coding.adapters.gh_pr import GhPullRequestOpener, PullRequestError
from bob.coding.adapters.git_clone import CloneError, GitClone
from bob.coding.adapters.git_worktree import GitWorktree, WorktreeError

__all__ = [
    "ClaudeRunError",
    "CloneError",
    "GhPullRequestOpener",
    "GitClone",
    "GitWorktree",
    "PullRequestError",
    "SubprocessClaudeRunner",
    "WorktreeError",
]
