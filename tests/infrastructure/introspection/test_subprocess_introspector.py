# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for SubprocessRepoIntrospector (BOB-017 Phase A .1).

The adapter realises :class:`bob.domain.ports.RepoIntrospector` by shelling out to
local ``beadloom`` / ``bd`` via ``asyncio.create_subprocess_exec`` (NEVER a shell)
against a FIXED allowlist of read-only subcommands, and reading source files only
after the :class:`~bob.domain.introspection.privacy_guard.PrivacyGuard` allows the
path. The subprocess boundary is injected as a fake here so the tests are
deterministic and never actually spawn a process; the file reader runs against a
tmp repo layout.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.domain.introspection.privacy_guard import PrivacyGuard
from bob.infrastructure.introspection.subprocess_introspector import (
    DeniedPathError,
    DisallowedCommandError,
    SubprocessRepoIntrospector,
    _ExecRunner,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeRunner:
    """Records the argv it was asked to run and returns canned stdout."""

    def __init__(self, stdout: str = "ok-output", *, delay: float = 0.0) -> None:
        self.calls: list[list[str]] = []
        self.seen_timeout: float = 0.0
        self._stdout = stdout
        self._delay = delay

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.seen_timeout = timeout
        self.calls.append(list(argv))
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout


def _make(
    tmp_path: Path,
    runner: _FakeRunner,
    *,
    max_output_chars: int = 10_000,
    timeout: float = 5.0,
) -> SubprocessRepoIntrospector:
    return SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path),
        runner=runner,
        max_output_chars=max_output_chars,
        timeout=timeout,
        beadloom_bin="beadloom",
        bd_bin="bd",
    )


# --- allowlist enforcement ----------------------------------------------------


@pytest.mark.asyncio
async def test_architecture_context_runs_beadloom_ctx(tmp_path: Path) -> None:
    runner = _FakeRunner("graph-ctx")
    intro = _make(tmp_path, runner)

    out = await intro.architecture_context("bob")

    assert out == "graph-ctx"
    assert runner.calls == [["beadloom", "ctx", "bob"]]


@pytest.mark.asyncio
async def test_search_code_runs_beadloom_search(tmp_path: Path) -> None:
    runner = _FakeRunner("hits")
    intro = _make(tmp_path, runner)

    await intro.search_code("privacy guard")

    assert runner.calls == [["beadloom", "search", "privacy guard"]]


@pytest.mark.asyncio
async def test_list_tasks_runs_bd_ready(tmp_path: Path) -> None:
    runner = _FakeRunner("ready-beads")
    intro = _make(tmp_path, runner)

    await intro.list_tasks("")

    assert runner.calls == [["bd", "ready"]]


@pytest.mark.asyncio
async def test_list_tasks_with_query_runs_bd_show(tmp_path: Path) -> None:
    runner = _FakeRunner("bead-detail")
    intro = _make(tmp_path, runner)

    await intro.list_tasks("bob-9eh")

    assert runner.calls == [["bd", "show", "bob-9eh"]]


@pytest.mark.asyncio
async def test_runner_never_invoked_for_disallowed_command(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", "init")  # not on the read allowlist

    assert runner.calls == []  # refused, NOT executed


@pytest.mark.asyncio
async def test_disallowed_binary_is_refused(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("rm", "ready")

    assert runner.calls == []


@pytest.mark.asyncio
async def test_argument_flags_that_could_inject_are_refused(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    # A flag-looking arg must never be passed through to a subcommand.
    with pytest.raises(DisallowedCommandError):
        await intro._run("bd", "show", "--exec=rm -rf /")

    assert runner.calls == []


# --- output truncation + sanitization -----------------------------------------


@pytest.mark.asyncio
async def test_output_is_truncated_to_cap(tmp_path: Path) -> None:
    runner = _FakeRunner("x" * 5000)
    intro = _make(tmp_path, runner, max_output_chars=100)

    out = await intro.architecture_context("bob")

    assert len(out) <= 100 + 64  # cap + a short truncation marker
    assert out.startswith("x" * 100)


@pytest.mark.asyncio
async def test_output_is_sanitized(tmp_path: Path) -> None:
    runner = _FakeRunner("TELEGRAM_TOKEN=123:abcDEF\nrest")
    intro = _make(tmp_path, runner)

    out = await intro.list_tasks("")

    assert "123:abcDEF" not in out
    assert "REDACTED" in out


# --- timeout wiring -----------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_is_passed_to_runner(tmp_path: Path) -> None:
    runner = _FakeRunner("ok")
    intro = SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path), runner=runner, timeout=2.5
    )

    await intro.architecture_context("bob")

    assert runner.seen_timeout == 2.5


# --- read_file via the guard --------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_reads_allowed_source(tmp_path: Path) -> None:
    src = tmp_path / "src" / "bob" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("line1\nline2\nline3\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/bob/app.py", max_lines=2)

    assert "line1" in out
    assert "line2" in out
    assert "line3" not in out  # capped at max_lines


@pytest.mark.asyncio
async def test_read_file_refuses_guarded_path_without_touching_disk(
    tmp_path: Path,
) -> None:
    # Lay down a real secret file so we can prove it is never opened.
    soul = tmp_path / "data" / "soul" / "SOUL.md"
    soul.parent.mkdir(parents=True)
    soul.write_text("DEEP_PRIVATE_SOUL_CONTENT", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DeniedPathError):
        await intro.read_file("data/soul/SOUL.md", max_lines=100)


@pytest.mark.asyncio
async def test_read_file_refuses_env_without_reading(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_TOKEN=should-never-leak", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DeniedPathError):
        await intro.read_file(".env", max_lines=100)


@pytest.mark.asyncio
async def test_read_file_sanitizes_returned_content(tmp_path: Path) -> None:
    src = tmp_path / "src" / "leaky.py"
    src.parent.mkdir(parents=True)
    src.write_text("API_KEY=sk-abcdef0123456789secret\ncode = 1\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/leaky.py", max_lines=10)

    assert "sk-abcdef0123456789secret" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_read_file_missing_allowed_file_returns_refusal(tmp_path: Path) -> None:
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/does_not_exist.py", max_lines=10)

    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_read_file_on_directory_returns_refusal(tmp_path: Path) -> None:
    # An allowed path that is a directory must not raise — honest refusal instead.
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/pkg", max_lines=10)

    assert "not found" in out.lower()


# --- default exec runner (real subprocess, no shell) --------------------------


@pytest.mark.asyncio
async def test_default_exec_runner_captures_stdout() -> None:
    runner = _ExecRunner()
    out = await runner(["printf", "hello-world"], timeout=5.0)

    assert "hello-world" in out


@pytest.mark.asyncio
async def test_default_exec_runner_times_out() -> None:
    runner = _ExecRunner()
    out = await runner(["sleep", "5"], timeout=0.1)

    assert "timed out" in out.lower()
