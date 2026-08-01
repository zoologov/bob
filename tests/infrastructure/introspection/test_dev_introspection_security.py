# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 SECURITY gap-fill for the read-only dev-introspection adapter (BOB-081.3).

BOB-081.1 already unit-tested the happy forms + the coarse write/injection refusals.
This module fills the SECURITY-CRITICAL gaps the review bead (.4) will audit against,
without duplicating .1:

* argument-injection VECTORS the .1 tests did not enumerate — a pipe, a ``$()``
  substitution, an absolute path, a ``../`` traversal, embedded whitespace — reaching
  ``show_task`` / ``task_comments`` are REFUSED and NEVER reach the (fake) subprocess;
* the sanitiser fires on git AND tracker output for MORE secret shapes than .1's single
  Telegram-token case: an ``sk-`` key, an ``API_KEY=`` assignment;
* the PORT SURFACE a model actually reaches (``recent_commits`` / ``tasks_by_status`` /
  ``show_task`` / ``task_comments``) cannot be steered into a WRITE — a status that is a
  write verb collapses to the plain unfiltered list, a huge count is clamped, and no
  argv ever carries an injected token.

The subprocess boundary is a recording fake, so nothing spawns; a refused call is proven
by ``runner.calls == []``.
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


class _RecordingRunner:
    """Records every argv it is asked to run; returns canned stdout (never spawns)."""

    def __init__(self, stdout: str = "ok") -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        return self._stdout


def _make(tmp_path: Path, runner: _RecordingRunner) -> SubprocessRepoIntrospector:
    return SubprocessRepoIntrospector(PrivacyGuard(tmp_path), runner=runner)


# The injection vectors a malicious id could carry — a flag, shell metacharacters, a
# command substitution, a path traversal, an absolute path, embedded whitespace. Each
# must be refused by ``validate_bead_id`` BEFORE any argv is built.
_INJECTION_IDS = [
    "BOB-1 | cat /etc/passwd",
    "BOB-1; rm -rf /",
    "BOB-1 && whoami",
    "$(whoami)",
    "`id`",
    "../../etc/passwd",
    "/etc/passwd",
    "--exec=rm -rf /",
    "-n 9999",
    "BOB-1 extra",
]


@pytest.mark.parametrize("bad_id", _INJECTION_IDS)
@pytest.mark.asyncio
async def test_show_task_refuses_injection_and_never_spawns(
    tmp_path: Path, bad_id: str
) -> None:
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(ValueError, match="bead"):
        await intro.show_task(bad_id)

    assert runner.calls == []  # the malicious id never reached a subprocess


@pytest.mark.parametrize("bad_id", _INJECTION_IDS)
@pytest.mark.asyncio
async def test_task_comments_refuses_injection_and_never_spawns(
    tmp_path: Path, bad_id: str
) -> None:
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(ValueError, match="bead"):
        await intro.task_comments(bad_id)

    assert runner.calls == []


# --- sanitiser fires on more secret shapes, across git AND tracker output ------


@pytest.mark.asyncio
async def test_recent_commits_output_redacts_sk_key(tmp_path: Path) -> None:
    runner = _RecordingRunner("abc123 leaked sk-abcdef0123456789secret in a commit")
    intro = _make(tmp_path, runner)

    out = await intro.recent_commits(10)

    assert "sk-abcdef0123456789secret" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_task_comments_output_redacts_api_key(tmp_path: Path) -> None:
    runner = _RecordingRunner("CHECKPOINT: set API_KEY=super-secret-value-123456")
    intro = _make(tmp_path, runner)

    out = await intro.task_comments("BOB-076")

    assert "super-secret-value-123456" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_show_task_output_redacts_telegram_token(tmp_path: Path) -> None:
    runner = _RecordingRunner("detail TELEGRAM_TOKEN=123456789:AAbbCCddEEffGG body")
    intro = _make(tmp_path, runner)

    out = await intro.show_task("BOB-081")

    assert "123456789:AAbbCCddEEffGG" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_tasks_by_status_output_is_sanitized(tmp_path: Path) -> None:
    runner = _RecordingRunner("○ bob-1 task sk-abcdef0123456789secret")
    intro = _make(tmp_path, runner)

    out = await intro.tasks_by_status("open")

    assert "sk-abcdef0123456789secret" not in out
    assert "REDACTED" in out


# --- the model-facing PORT SURFACE cannot be steered into a write --------------


@pytest.mark.asyncio
async def test_status_that_is_a_write_verb_collapses_to_plain_list(
    tmp_path: Path,
) -> None:
    # A model passing a mutating/unknown "status" (e.g. a shell-injected value) is
    # normalised to None → the plain unfiltered ``bd list``; no injected token in argv.
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    for hostile in ("closed; drop", "delete", "--status=x", "close"):
        runner.calls.clear()
        await intro.tasks_by_status(hostile)
        assert runner.calls == [["bd", "list"]]


@pytest.mark.asyncio
async def test_recent_commits_count_is_always_bounded(tmp_path: Path) -> None:
    # A model asking for an unbounded/absurd history is clamped to the [1,50] window,
    # so ``git log`` can never be a flood — the count slot is a pure integer, unquotable.
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    await intro.recent_commits(10_000)
    assert runner.calls == [["git", "log", "--oneline", "-n", "50"]]


@pytest.mark.asyncio
async def test_no_git_write_form_is_expressible_via_run(tmp_path: Path) -> None:
    # Defence-in-depth enumeration through the raw ``_run`` seam: every mutating/state
    # git subcommand is refused before exec (only read-only ``log`` fixed forms pass).
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    for sub in ("commit", "push", "checkout", "reset", "rebase", "merge", "tag", "show"):
        with pytest.raises(DisallowedCommandError):
            await intro._run("git", sub)

    assert runner.calls == []


@pytest.mark.asyncio
async def test_no_bd_write_form_is_expressible_via_run(tmp_path: Path) -> None:
    # Defence-in-depth: every mutating ``bd`` subcommand is refused (only read-only
    # ready/show/list/comments pass the allowlist).
    runner = _RecordingRunner()
    intro = _make(tmp_path, runner)

    for sub in ("create", "update", "close", "delete", "dep", "comment"):
        with pytest.raises(DisallowedCommandError):
            await intro._run("bd", sub, "BOB-1")

    assert runner.calls == []
