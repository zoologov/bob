# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for InteractiveClaudeRunner + encode_user_message (BOB-083 .2).

The persistent bidirectional runner realises :class:`bob.coding.ports.InteractiveRunner`:
it spawns ``claude -p --input-format stream-json --output-format stream-json --verbose
--permission-mode <mode>`` via ``asyncio.create_subprocess_exec`` (NEVER a shell) with an
OPEN stdin, RETAINS the process handle, feeds owner text as one stream-json ``user`` frame,
reads stdout as NDJSON, and terminates (then kills after a grace) on close. The bidirectional
subprocess boundary is INJECTED as a fake here so the tests are deterministic and never spawn
the real ``claude``: the fake records fed bytes / terminate / kill and yields scripted lines.

``encode_user_message`` is the pure core (mutation target): text -> ONE stream-json ``user``
input line that claude's ``--input-format stream-json`` accepts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.claude_runner import ClaudeRunError
from bob.coding.adapters.interactive_runner import (
    InteractiveClaudeRunner,
    InteractiveRunError,
    encode_user_message,
)
from bob.coding.ports import InteractiveRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping


# --------------------------------------------------------------------------- #
# encode_user_message — the pure core (mutation target)
# --------------------------------------------------------------------------- #


def _content_text(line: str) -> str:
    """Drill into the encoded stream-json ``user`` frame and return its one text block."""
    frame = json.loads(line)
    assert isinstance(frame, dict)
    message = frame["message"]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, dict)
    text = block["text"]
    assert isinstance(text, str)
    return text


def test_encode_user_message_is_a_valid_stream_json_user_frame() -> None:
    frame = json.loads(encode_user_message("hello Bob"))

    assert isinstance(frame, dict)
    assert frame["type"] == "user"
    message = frame["message"]
    assert isinstance(message, dict)
    assert message["role"] == "user"
    assert message["content"] == [{"type": "text", "text": "hello Bob"}]


def test_encode_user_message_is_a_single_line() -> None:
    line = encode_user_message("first\nsecond")

    # ONE stream-json object per line — the payload's own newline must be escaped,
    # never split the frame across two NDJSON lines.
    assert "\n" not in line


def test_encode_user_message_escapes_special_characters() -> None:
    text = 'quote " backslash \\ newline \n tab \t'

    assert _content_text(encode_user_message(text)) == text


def test_encode_user_message_round_trips_unicode() -> None:
    text = "Привет, Боб — как дела?"

    assert _content_text(encode_user_message(text)) == text


def test_encode_user_message_handles_empty_text() -> None:
    assert _content_text(encode_user_message("")) == ""


# --------------------------------------------------------------------------- #
# InteractiveClaudeRunner — over a FAKE bidirectional process
# --------------------------------------------------------------------------- #


class _FakeProcess:
    """A scripted bidirectional process: records fed bytes / terminate / kill."""

    def __init__(
        self, lines: list[str] | None = None, *, exit_on_terminate: bool = True
    ) -> None:
        self.fed: list[bytes] = []
        self.terminated = 0
        self.killed = 0
        self.waits = 0
        self._lines = lines or []
        self._exit_on_terminate = exit_on_terminate
        self._alive = True

    async def feed(self, data: bytes) -> None:
        self.fed.append(data)

    async def read_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    def terminate(self) -> None:
        self.terminated += 1
        if self._exit_on_terminate:
            self._alive = False

    def kill(self) -> None:
        self.killed += 1
        self._alive = False

    async def wait(self, *, timeout: float | None = None) -> bool:
        self.waits += 1
        return not self._alive

    @property
    def alive(self) -> bool:
        return self._alive


class _FakeSpawner:
    """Records the argv / cwd, returns the pre-built fake process."""

    def __init__(self, proc: _FakeProcess) -> None:
        self.proc = proc
        self.calls: list[list[str]] = []
        self.seen_cwd: str | None = None

    async def __call__(self, argv: list[str], *, cwd: str) -> _FakeProcess:
        self.calls.append(list(argv))
        self.seen_cwd = cwd
        return self.proc


async def _collect(
    events: AsyncIterator[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return [event async for event in events]


async def test_open_spawns_with_the_interactive_argv() -> None:
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner, claude_bin="my-claude")

    await runner.open("/work/dir", mode="acceptEdits")

    assert spawner.calls[0] == [
        "my-claude",
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
    ]
    assert spawner.seen_cwd == "/work/dir"


@pytest.mark.parametrize("mode", ["bypassPermissions", "plan; rm -rf /", "", "PLAN"])
async def test_open_rejects_a_mode_outside_the_allowlist(mode: str) -> None:
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner)

    with pytest.raises(ClaudeRunError):
        await runner.open("/w", mode=mode)

    # A rejected mode never spawns a process.
    assert spawner.calls == []


async def test_reopen_while_a_process_is_live_is_refused() -> None:
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open("/w", mode="plan")

    with pytest.raises(InteractiveRunError):
        await runner.open("/w", mode="plan")

    assert len(spawner.calls) == 1


async def test_feed_writes_the_encoded_frame_to_stdin() -> None:
    proc = _FakeProcess()
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")

    await runner.feed("do the thing")

    assert proc.fed == [encode_user_message("do the thing").encode("utf-8") + b"\n"]


async def test_events_yields_scripted_stream_json_lines() -> None:
    proc = _FakeProcess(
        [
            '{"type": "system", "subtype": "init"}\n',
            "not json at all\n",
            '{"type": "assistant", "n": 1}\n',
            "\n",
            '{"type": "result"}',
        ]
    )
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")

    events = await _collect(runner.events())

    assert [event["type"] for event in events] == ["system", "assistant", "result"]


async def test_close_terminates_and_is_idempotent() -> None:
    proc = _FakeProcess()
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")

    await runner.close()
    await runner.close()

    assert proc.terminated == 1
    assert proc.killed == 0
    assert proc.waits >= 1


async def test_close_kills_when_terminate_does_not_stop_the_process() -> None:
    proc = _FakeProcess(exit_on_terminate=False)
    runner = InteractiveClaudeRunner(
        spawner=_FakeSpawner(proc), terminate_grace=0.01
    )
    await runner.open("/w", mode="plan")

    await runner.close()

    assert proc.terminated == 1
    assert proc.killed == 1


async def test_close_before_open_does_not_crash() -> None:
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(_FakeProcess()))

    await runner.close()  # no process yet — best-effort no-op


async def test_feed_after_close_does_not_crash() -> None:
    proc = _FakeProcess()
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")
    await runner.close()

    await runner.feed("late message")

    # A dead/closed process is guarded — the frame is dropped, never written.
    assert proc.fed == []


async def test_feed_before_open_does_not_crash() -> None:
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(_FakeProcess()))

    await runner.feed("no process yet")  # best-effort no-op, never raises


def test_interactive_runner_satisfies_the_port() -> None:
    assert isinstance(InteractiveClaudeRunner(), InteractiveRunner)
