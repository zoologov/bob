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

from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.claude_runner import (
    ClaudeRunError,
    SubprocessClaudeRunner,
)
from bob.domain.ports import ClaudeCodeRunner

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
