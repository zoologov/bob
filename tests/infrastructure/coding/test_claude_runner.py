# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for SubprocessClaudeRunner (BOB-039 .2).

The adapter realises :class:`bob.domain.ports.ClaudeCodeRunner` by running the local
``claude`` CLI headless via ``asyncio.create_subprocess_exec`` (NEVER a shell), with
``--output-format stream-json`` and a FIXED ``--permission-mode`` allowlist, then
reading stdout as NDJSON line-by-line, ``json.loads``-ing each line and yielding the
parsed event. The streaming subprocess boundary is INJECTED as a fake here so the
tests are deterministic and never spawn the real ``claude`` (not installed in this
env): the fake yields canned NDJSON lines, records the argv / cwd / timeout it is
handed, and signals when its generator was closed (the early-break cleanup path).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.adapters.claude_runner import (
    _STREAM_LIMIT,
    ClaudeRunError,
    SubprocessClaudeRunner,
    _ExecStreamRunner,
)
from bob.coding.ports import ClaudeCodeRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping


class _FakeStream:
    """A scripted stream runner: yields canned lines, records the invocation."""

    def __init__(self, lines: list[str]) -> None:
        self.calls: list[list[str]] = []
        self.seen_cwd: str | None = None
        self.seen_timeout: float = 0.0
        self.closed: bool = False
        self._lines = lines

    def __call__(
        self, argv: list[str], *, cwd: str, timeout: float
    ) -> AsyncIterator[str]:
        self.calls.append(list(argv))
        self.seen_cwd = cwd
        self.seen_timeout = timeout
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        try:
            for line in self._lines:
                yield line
        finally:
            self.closed = True


async def _collect(
    events: AsyncIterator[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return [event async for event in events]


async def test_run_builds_the_stream_json_claude_argv() -> None:
    runner = _FakeStream(['{"type": "system"}'])
    claude = SubprocessClaudeRunner(runner=runner, claude_bin="my-claude")

    await _collect(claude.run("/work/dir", "do the task", mode="plan"))

    argv = runner.calls[0]
    assert argv == [
        "my-claude",
        "-p",
        "do the task",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "plan",
    ]
    assert runner.seen_cwd == "/work/dir"


async def test_run_passes_the_execute_mode_through() -> None:
    runner = _FakeStream([])
    claude = SubprocessClaudeRunner(runner=runner)

    await _collect(claude.run("/w", "task", mode="acceptEdits"))

    assert runner.calls[0][-1] == "acceptEdits"


@pytest.mark.parametrize("mode", ["bypassPermissions", "plan; rm -rf /", "", "PLAN"])
async def test_run_rejects_a_mode_outside_the_allowlist(mode: str) -> None:
    runner = _FakeStream([])
    claude = SubprocessClaudeRunner(runner=runner)

    with pytest.raises(ClaudeRunError):
        await _collect(claude.run("/w", "task", mode=mode))

    # A rejected mode never reaches the subprocess.
    assert runner.calls == []


async def test_run_parses_a_multi_line_ndjson_stream_into_events() -> None:
    runner = _FakeStream(
        [
            '{"type": "system", "subtype": "init"}\n',
            '{"type": "assistant", "n": 1}\n',
            '{"type": "result", "subtype": "success"}\n',
        ]
    )
    claude = SubprocessClaudeRunner(runner=runner)

    events = await _collect(claude.run("/w", "task", mode="plan"))

    assert [event["type"] for event in events] == ["system", "assistant", "result"]


async def test_run_skips_blank_and_garbage_lines() -> None:
    runner = _FakeStream(
        [
            "\n",
            "not json at all",
            '{"type": "ok"}\n',
            "{ partial json",
            "   ",
            '{"type": "done"}',
        ]
    )
    claude = SubprocessClaudeRunner(runner=runner)

    events = await _collect(claude.run("/w", "task", mode="plan"))

    assert [event["type"] for event in events] == ["ok", "done"]


async def test_run_skips_a_non_object_json_line() -> None:
    runner = _FakeStream(["[1, 2, 3]", "42", '{"type": "ok"}'])
    claude = SubprocessClaudeRunner(runner=runner)

    events = await _collect(claude.run("/w", "task", mode="plan"))

    assert [event["type"] for event in events] == ["ok"]


async def test_run_enforces_the_max_events_bound_and_closes_the_stream() -> None:
    runner = _FakeStream([f'{{"i": {i}}}' for i in range(100)])
    claude = SubprocessClaudeRunner(runner=runner, max_events=3)

    events = await _collect(claude.run("/w", "task", mode="plan"))

    assert len(events) == 3
    # Breaking early must close the generator (kill/reap the real process).
    assert runner.closed is True


async def test_run_enforces_the_max_bytes_bound() -> None:
    big = '{"x": "' + "a" * 1000 + '"}'
    runner = _FakeStream([big, big, big, '{"type": "late"}'])
    claude = SubprocessClaudeRunner(runner=runner, max_bytes=1500)

    events = await _collect(claude.run("/w", "task", mode="plan"))

    # The byte budget cuts the stream off before the late event.
    assert all(event.get("type") != "late" for event in events)


async def test_run_passes_the_configured_timeout() -> None:
    runner = _FakeStream([])
    claude = SubprocessClaudeRunner(runner=runner, timeout=123.0)

    await _collect(claude.run("/w", "task", mode="plan"))

    assert runner.seen_timeout == 123.0


def test_claude_runner_satisfies_the_runner_port() -> None:
    assert isinstance(SubprocessClaudeRunner(), ClaudeCodeRunner)


# --------------------------------------------------------------------------- #
# The real exec transport: 64 KiB StreamReader limit (BOB-084 .1)
# --------------------------------------------------------------------------- #


class _RaisingStdout:
    """A stdout whose ``readline`` raises the overlong-line ``ValueError``.

    asyncio surfaces a ``StreamReader`` ``LimitOverrunError`` ("Separator is found, but
    chunk is longer than limit") as a ``ValueError`` — the exact crash a claude line past
    the buffer limit produces, which the fake scripted-line runner cannot reproduce.
    """

    async def readline(self) -> bytes:
        raise ValueError("Separator is found, but chunk is longer than limit")


class _FakeExecProc:
    """Minimal stand-in for ``asyncio.subprocess.Process`` with a raising stdout."""

    def __init__(self, stdout: _RaisingStdout) -> None:
        self.stdout = stdout
        self.stderr = None
        self.returncode: int | None = 0  # already exited -> kill is skipped

    def kill(self) -> None: ...

    async def wait(self) -> int:
        return 0


def _as_process(fake: _FakeExecProc) -> asyncio.subprocess.Process:
    return cast("asyncio.subprocess.Process", fake)


async def test_exec_stream_runner_ends_gracefully_on_an_overlong_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_exec(
        *argv: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        return _as_process(_FakeExecProc(_RaisingStdout()))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "create_subprocess_exec", fake_exec)
        with caplog.at_level(logging.WARNING):
            lines = [
                line
                async for line in _ExecStreamRunner()(
                    ["claude"], cwd="/w", timeout=5.0
                )
            ]

    # The overlong-line ValueError ends the stream instead of crashing the read loop.
    assert lines == []
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_exec_stream_runner_passes_the_stream_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_exec(
        *argv: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        captured.update(kwargs)
        return _as_process(_FakeExecProc(_RaisingStdout()))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async for _ in _ExecStreamRunner()(["claude"], cwd="/w", timeout=5.0):
        pass

    assert captured["limit"] == _STREAM_LIMIT
    assert _STREAM_LIMIT == 16 * 1024 * 1024
