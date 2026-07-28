# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for GhPullRequestOpener (BOB-039 .2).

The adapter realises :class:`bob.domain.ports.PullRequestOpener` by running
``gh pr create --base main --head <branch> --title <title> --body <body>`` as a
FIXED-form, shell-free invocation and returning the PR url from stdout. The
subprocess boundary is injected as a fake here so the tests never spawn the real
``gh``. 🔴 The safety invariant — Bob opens a PR and STOPS; there is NO merge and NO
push-to-main path — is asserted both behaviourally (the opener only ever runs ``gh pr
create``) and by absence (the module source contains no ``merge`` / ``push`` code).
"""

from __future__ import annotations

import inspect

import pytest

import bob.coding.adapters.gh_pr as gh_pr_module
from bob.coding.adapters.gh_pr import GhPullRequestOpener, PullRequestError
from bob.coding.ports import PullRequestOpener

_URL = "https://github.com/owner/repo/pull/42"


class _FakeCommand:
    """A scripted command runner: records argv, returns the canned PR url on stdout."""

    def __init__(self, *, stdout: str = _URL) -> None:
        self.calls: list[list[str]] = []
        self.seen_timeout: float = 0.0
        self._stdout = stdout

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.seen_timeout = timeout
        self.calls.append(list(argv))
        return self._stdout


async def test_open_builds_the_fixed_gh_pr_create_argv() -> None:
    runner = _FakeCommand()
    opener = GhPullRequestOpener(runner=runner, gh_bin="my-gh")

    await opener.open("bob/fix-typo", "Fix the typo", "It was bugging me.")

    assert runner.calls[0] == [
        "my-gh",
        "pr",
        "create",
        "--base",
        "main",
        "--head",
        "bob/fix-typo",
        "--title",
        "Fix the typo",
        "--body",
        "It was bugging me.",
    ]


async def test_open_returns_the_pr_url_from_stdout() -> None:
    runner = _FakeCommand(stdout=f"  {_URL}\n")
    opener = GhPullRequestOpener(runner=runner)

    url = await opener.open("bob/x", "t", "b")

    assert url == _URL


async def test_open_targets_a_configurable_base() -> None:
    runner = _FakeCommand()
    opener = GhPullRequestOpener(runner=runner, base="develop")

    await opener.open("bob/x", "t", "b")

    argv = runner.calls[0]
    assert argv[argv.index("--base") + 1] == "develop"


@pytest.mark.parametrize("branch", ["main", "BOB/x", "bob/../etc", "feature/x", "bob/"])
async def test_open_rejects_a_branch_outside_the_bob_slug_form(branch: str) -> None:
    runner = _FakeCommand()
    opener = GhPullRequestOpener(runner=runner)

    with pytest.raises(PullRequestError):
        await opener.open(branch, "t", "b")

    assert runner.calls == []


async def test_open_only_ever_runs_gh_pr_create() -> None:
    # The opener creates a PR and STOPS — it never merges, never pushes to main.
    runner = _FakeCommand()
    opener = GhPullRequestOpener(runner=runner)

    await opener.open("bob/x", "t", "b")
    await opener.open("bob/y", "t", "b")

    for argv in runner.calls:
        assert argv[1:3] == ["pr", "create"]
        assert "merge" not in argv
        assert "push" not in argv


def test_module_has_no_merge_or_push_to_main_path() -> None:
    # Safety by absence: there is physically no merge / push-to-main code here.
    source = inspect.getsource(gh_pr_module)
    assert "merge" not in source
    assert "push" not in source


def test_gh_opener_satisfies_the_pull_request_opener_port() -> None:
    assert isinstance(GhPullRequestOpener(), PullRequestOpener)
