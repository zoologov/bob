# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""Safe coding-branch validation — shared by the worktree + PR adapters (BOB-039 .2).

A single pure predicate: a coding branch must be the exact ``bob/<slug>`` shape the
domain's :func:`bob.coding.naming.worktree_branch` produces (lowercase ascii
``[a-z0-9]`` with internal hyphens). Re-validating the shape at the infrastructure
boundary closes path-injection (``bob/../etc``, slashes, whitespace, uppercase never
pass) BEFORE a branch reaches ``git`` or ``gh``, so a malformed branch is refused
rather than executed. Deterministic, no I/O.
"""

from __future__ import annotations

import re

__all__ = ["is_safe_branch"]

# A coding branch: the literal ``bob/`` prefix + a non-empty slug of lowercase ascii
# letters/digits with internal single hyphens. No ``..``, no slash, no whitespace, no
# uppercase — so it can never smuggle a path segment or a flag into an argv slot.
_BRANCH_RE = re.compile(r"^bob/[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_safe_branch(branch: str) -> bool:
    """Whether ``branch`` is the safe ``bob/<slug>`` coding-branch shape."""
    return bool(_BRANCH_RE.match(branch))
