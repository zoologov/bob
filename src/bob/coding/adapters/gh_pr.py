# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""GhPullRequestOpener — open a PR for a coding session's branch (BOB-039 .2).

The infrastructure adapter realising :class:`bob.domain.ports.PullRequestOpener`. It
runs, as a FIXED-form shell-free invocation (the title/body are discrete argv items,
never interpolated into a shell):

    gh pr create --base main --head <branch> --title <title> --body <body>

and returns the PR url from stdout. The branch is validated to the ``bob/<slug>``
shape before ``gh`` runs.

SAFETY INVARIANT: Bob opens a PR and STOPS. The only ``gh`` form this module ever
builds is ``pr create`` — there is DELIBERATELY no integrate-to-trunk path here (no
``gh pr <integrate>``, no ``git`` write to the protected branch). The OWNER lands the
change by hand. That physical absence is part of the gated-autonomy guarantee, not an
oversight — and a test asserts the dangerous tokens never appear in this source.
"""

from __future__ import annotations

from bob.coding.adapters._branch import is_safe_branch
from bob.coding.adapters._exec import (
    DEFAULT_TIMEOUT_S,
    CommandRunner,
    ExecRunner,
)

__all__ = ["GhPullRequestOpener", "PullRequestError"]


class PullRequestError(Exception):
    """A pull-request open was refused (unsafe branch) before ``gh`` ran."""


class GhPullRequestOpener:
    """Open a pull request via fixed-form, shell-free ``gh pr create`` only."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        gh_bin: str = "gh",
        base: str = "main",
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._runner: CommandRunner = runner or ExecRunner()
        self._gh_bin = gh_bin
        self._base = base
        self._timeout = timeout

    async def open(self, branch: str, title: str, body: str) -> str:
        """Open a PR for ``branch`` and return its url (owner lands it; Bob only opens)."""
        if not is_safe_branch(branch):
            raise PullRequestError(
                f"branch {branch!r} is not a safe bob/<slug> coding branch"
            )
        argv = [
            self._gh_bin,
            "pr",
            "create",
            "--base",
            self._base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ]
        stdout = await self._runner(argv, timeout=self._timeout)
        return stdout.strip()
