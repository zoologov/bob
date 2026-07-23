# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the DEFAULT subprocess boundaries of the coding adapters (BOB-039 .2).

The adapter tests drive an INJECTED fake runner — they never touch the real
``create_subprocess_exec`` path. This file covers those remaining default branches
(``ExecRunner`` for git/gh, ``_ExecStreamRunner`` for claude) WITHOUT ever spawning a
real ``git`` / ``gh`` / ``claude`` (none are exercised here): ``asyncio
.create_subprocess_exec`` is monkeypatched to a deterministic fake process so the
success, non-zero-exit, timeout → kill → reap, and NDJSON line-streaming + early-break
kill branches are all driven with no real process. The argv reaching the OS boundary
is asserted (no shell), proving the adapters hand the right exec call to the kernel.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters import claude_runner, gh_pr
from bob.coding.adapters._exec import CommandError, ExecRunner
from bob.coding.adapters.claude_runner import SubprocessClaudeRunner
from bob.coding.adapters.gh_pr import GhPullRequestOpener

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class _FakeProc:
    """A scripted ``asyncio.subprocess.Process`` for the capture (communicate) path."""

    def __init__(
        self,
        *,
        returncode: int | None = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.Event().wait()
        return (self._stdout, self._stderr)

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return self.returncode if self.returncode is not None else 0


def _patch_exec(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    proc: _FakeProc,
    recorder: list[list[str]],
) -> None:
    async def _fake_exec(*argv: str, **_kwargs: object) -> _FakeProc:
        recorder.append(list(argv))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    # The module imports the symbol into its own namespace via ``asyncio.`` — patching
    # asyncio is enough since both runners call ``asyncio.create_subprocess_exec``.
    _ = module


# --- ExecRunner (git / gh) ----------------------------------------------------


async def test_exec_runner_returns_stdout_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv_seen: list[list[str]] = []
    _patch_exec(
        monkeypatch, gh_pr, _FakeProc(returncode=0, stdout=b"the-url\n"), argv_seen
    )
    opener = GhPullRequestOpener(gh_bin="gh")

    url = await opener.open("bob/x", "t", "b")

    assert url == "the-url"
    assert argv_seen[0][0] == "gh"
    assert argv_seen[0][1:3] == ["pr", "create"]


async def test_exec_runner_raises_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_exec(
        monkeypatch, gh_pr, _FakeProc(returncode=1, stderr=b"boom"), []
    )
    opener = GhPullRequestOpener()

    with pytest.raises(CommandError):
        await opener.open("bob/x", "t", "b")


async def test_exec_runner_times_out_kills_and_reaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProc(hang=True)
    _patch_exec(monkeypatch, gh_pr, proc, [])
    opener = GhPullRequestOpener(timeout=0.01)

    with pytest.raises(CommandError, match="timed out"):
        await opener.open("bob/x", "t", "b")

    assert proc.killed is True
    assert proc.waited is True


def test_exec_runner_is_the_default_for_gh() -> None:
    assert isinstance(GhPullRequestOpener()._runner, ExecRunner)


# --- _ExecStreamRunner (claude) -----------------------------------------------


class _FakeStreamProc:
    """A scripted process whose ``stdout`` yields canned NDJSON lines then EOF."""

    def __init__(self, lines: list[bytes], *, hang: bool = False) -> None:
        # A still-running process reports ``returncode is None`` until it is reaped —
        # that None is exactly what drives the runner's kill-on-break branch.
        self.returncode: int | None = None
        self.stdout = _FakeStdout(lines, hang=hang)
        self.killed = False
        self.waited = False

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.waited = True
        return self.returncode if self.returncode is not None else 0


class _FakeStdout:
    """A scripted ``StreamReader``: returns queued lines, then ``b""`` (EOF)."""

    def __init__(self, lines: list[bytes], *, hang: bool = False) -> None:
        self._lines = list(lines)
        self._hang = hang

    async def readline(self) -> bytes:
        if self._hang:
            await asyncio.Event().wait()
        if self._lines:
            return self._lines.pop(0)
        return b""


def _patch_stream_exec(
    monkeypatch: pytest.MonkeyPatch, proc: _FakeStreamProc, recorder: list[list[str]]
) -> None:
    async def _fake_exec(*argv: str, **_kwargs: object) -> _FakeStreamProc:
        recorder.append(list(argv))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)


async def _collect(events: AsyncIterator[object]) -> list[object]:
    return [event async for event in events]


async def test_stream_runner_streams_ndjson_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeStreamProc(
        [b'{"type": "system"}\n', b'{"type": "result"}\n']
    )
    argv_seen: list[list[str]] = []
    _patch_stream_exec(monkeypatch, proc, argv_seen)
    runner = SubprocessClaudeRunner(claude_bin="claude")

    events = await _collect(runner.run("/w", "task", mode="plan"))

    assert len(events) == 2
    assert argv_seen[0][0] == "claude"
    assert "stream-json" in argv_seen[0]
    assert proc.waited is True


async def test_stream_runner_kills_the_process_on_early_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeStreamProc([b'{"i": 0}\n', b'{"i": 1}\n', b'{"i": 2}\n'])
    _patch_stream_exec(monkeypatch, proc, [])
    runner = SubprocessClaudeRunner(max_events=1)

    events = await _collect(runner.run("/w", "task", mode="plan"))

    assert len(events) == 1
    assert proc.killed is True
    assert proc.waited is True


async def test_stream_runner_times_out_and_reaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeStreamProc([], hang=True)
    _patch_stream_exec(monkeypatch, proc, [])
    runner = SubprocessClaudeRunner(timeout=0.01)

    events = await _collect(runner.run("/w", "task", mode="plan"))

    # A timeout cuts the stream cleanly (no events) and reaps the process.
    assert events == []
    assert proc.killed is True
    assert proc.waited is True


def test_module_namespaces_are_importable() -> None:
    # Guard against an accidental rename breaking the default-runner wiring.
    assert hasattr(claude_runner, "SubprocessClaudeRunner")
    assert hasattr(gh_pr, "GhPullRequestOpener")
