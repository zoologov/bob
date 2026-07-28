# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the git fixed-form allowlist + ``code_history`` (BOB-038 .1).

``git`` is added to the read-only allowlist as a set of FIXED invocation forms (the
same technique as ``bd list``'s arg-form allowlist): only ``git log`` with an exact
argv shape — a bounded ``--oneline -n <N> -- <path>`` over a safe repo-relative path,
or ``--grep=<BOB-key> --oneline`` — is ever built and validated. Any other git
subcommand, an extra flag, an out-of-form shape, or a path-injection is refused with
:class:`DisallowedCommandError` before any subprocess runs. The runner is faked so the
argv is asserted deterministically without spawning git.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    DisallowedCommandError,
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard

if TYPE_CHECKING:
    from pathlib import Path


class _FakeRunner:
    """Records the argv it was asked to run and returns canned stdout."""

    def __init__(self, stdout: str = "log-output") -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        return self._stdout


def _make(tmp_path: Path, runner: _FakeRunner) -> SubprocessRepoIntrospector:
    return SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path),
        runner=runner,
        beadloom_bin="beadloom",
        bd_bin="bd",
        git_bin="git",
    )


# --- the allowed fixed forms --------------------------------------------------


@pytest.mark.asyncio
async def test_code_history_for_a_path_runs_bounded_oneline_log(
    tmp_path: Path,
) -> None:
    runner = _FakeRunner("history")
    intro = _make(tmp_path, runner)

    out = await intro.code_history("src/bob/app.py")

    assert out == "history"
    assert len(runner.calls) == 1
    argv = runner.calls[0]
    # git log --oneline -n <N> -- <path> (bounded, path after the -- separator).
    assert argv[0] == "git"
    assert argv[1] == "log"
    assert argv[2] == "--oneline"
    assert argv[3] == "-n"
    assert argv[4].isdigit()
    assert argv[5] == "--"
    assert argv[6] == "src/bob/app.py"


@pytest.mark.asyncio
async def test_code_history_for_a_bead_key_runs_grep_log(tmp_path: Path) -> None:
    runner = _FakeRunner("grep-history")
    intro = _make(tmp_path, runner)

    out = await intro.code_history("BOB-031")

    assert out == "grep-history"
    assert runner.calls == [["git", "log", "--grep=BOB-031", "--oneline"]]


@pytest.mark.asyncio
async def test_code_history_for_a_lowercase_node_id_uses_grep(
    tmp_path: Path,
) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    await intro.code_history("bob-4be.1")

    assert runner.calls == [["git", "log", "--grep=bob-4be.1", "--oneline"]]


# --- refusals: subcommands, flags, path-injection -----------------------------


@pytest.mark.parametrize("sub", ["show", "diff", "push", "cat-file", "blame"])
@pytest.mark.asyncio
async def test_arbitrary_git_subcommand_is_refused(
    tmp_path: Path, sub: str
) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("git", sub, "--oneline")

    assert runner.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ("--oneline", "-C", "/etc", "--", "src/x.py"),
        ("--oneline", "--output=x", "--", "src/x.py"),
        ("--oneline", "--", "src/x.py", "--pretty=%H"),
        ("--all", "--oneline"),
        ("--grep=BOB-1", "--oneline", "--source"),
    ],
)
@pytest.mark.asyncio
async def test_extra_or_unknown_git_flags_are_refused(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("git", "log", *args)

    assert runner.calls == []


@pytest.mark.parametrize(
    "bad_path",
    ["../secrets.txt", "/etc/passwd", "src/../../escape", "-rf", ""],
)
@pytest.mark.asyncio
async def test_path_injection_is_refused(tmp_path: Path, bad_path: str) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro.code_history(bad_path)

    assert runner.calls == []


def test_validate_git_args_rejects_a_non_log_subcommand(tmp_path: Path) -> None:
    # Defence in depth: even called directly (past the _run subcommand gate), the
    # git arg validator refuses anything but ``log``.
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DisallowedCommandError):
        intro._validate_git_args("show", ("--oneline",))


@pytest.mark.asyncio
async def test_grep_form_rejects_a_non_bead_grep_value(tmp_path: Path) -> None:
    # A --grep value that is not a strict bead key is not an allowlisted form.
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("git", "log", "--grep=rm -rf /", "--oneline")

    assert runner.calls == []
