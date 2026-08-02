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

import asyncio
import json
import logging
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.adapters.claude_runner import _STREAM_LIMIT, ClaudeRunError
from bob.coding.adapters.interactive_runner import (
    InteractiveClaudeRunner,
    InteractiveRunError,
    _ExecInteractiveProcess,
    _ExecInteractiveSpawner,
    build_interactive_argv,
    encode_user_message,
    extract_session_id,
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


def test_encode_user_message_keeps_unicode_raw_not_ascii_escaped() -> None:
    # ``ensure_ascii=False`` is a real contract: the stream-json frame carries the raw
    # UTF-8 text, NOT ``\uXXXX`` escapes — so the line is compact and human-readable in the
    # owner's terminal. (Pins the encoder against an ``ensure_ascii=True``/default mutant.)
    line = encode_user_message("Привет")

    assert "Привет" in line
    assert "\\u" not in line


def test_encode_user_message_handles_empty_text() -> None:
    assert _content_text(encode_user_message("")) == ""


# --------------------------------------------------------------------------- #
# build_interactive_argv — the pure argv core (mutation target, BOB-087.D1)
# --------------------------------------------------------------------------- #

_FRESH_ARGV = [
    "claude",
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "acceptEdits",
]


def test_build_argv_fresh_is_the_baseline() -> None:
    # OFF path: no resume, no continue → byte-identical to the pre-D1 inline argv.
    assert build_interactive_argv("claude", mode="acceptEdits") == _FRESH_ARGV


def test_build_argv_threads_the_claude_bin_and_mode() -> None:
    argv = build_interactive_argv("my-claude", mode="plan")

    assert argv[0] == "my-claude"
    assert argv[-2:] == ["--permission-mode", "plan"]


def test_build_argv_resume_by_id_appends_resume_flag() -> None:
    argv = build_interactive_argv(
        "claude", mode="acceptEdits", resume_session_id="sess-123"
    )

    # The fresh baseline is preserved, then ``--resume <id>`` is appended.
    assert argv[: len(_FRESH_ARGV)] == _FRESH_ARGV
    assert argv[len(_FRESH_ARGV) :] == ["--resume", "sess-123"]


def test_build_argv_continue_appends_continue_flag() -> None:
    argv = build_interactive_argv("claude", mode="acceptEdits", continue_session=True)

    assert argv[: len(_FRESH_ARGV)] == _FRESH_ARGV
    assert argv[len(_FRESH_ARGV) :] == ["--continue"]


def test_build_argv_resume_by_id_takes_precedence_over_continue() -> None:
    argv = build_interactive_argv(
        "claude",
        mode="acceptEdits",
        resume_session_id="sess-9",
        continue_session=True,
    )

    # A concrete session id is more specific than "continue the latest" — it wins,
    # and ``--continue`` is NOT also emitted (never two resume strategies at once).
    assert argv[len(_FRESH_ARGV) :] == ["--resume", "sess-9"]
    assert "--continue" not in argv


def test_build_argv_empty_resume_id_is_treated_as_no_resume() -> None:
    # An empty id is not a real session — fall back to the fresh baseline (no --resume).
    assert build_interactive_argv("claude", mode="plan", resume_session_id="") == [
        "claude",
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "plan",
    ]


# --------------------------------------------------------------------------- #
# extract_session_id — the pure init-event core (mutation target, BOB-087.D1)
# --------------------------------------------------------------------------- #


def test_extract_session_id_reads_the_init_event() -> None:
    event = {"type": "system", "subtype": "init", "session_id": "sess-abc"}

    assert extract_session_id(event) == "sess-abc"


def test_extract_session_id_ignores_a_non_init_system_event() -> None:
    assert extract_session_id(
        {"type": "system", "subtype": "other", "session_id": "x"}
    ) is None


def test_extract_session_id_ignores_a_non_system_event() -> None:
    assert extract_session_id({"type": "assistant", "session_id": "x"}) is None


def test_extract_session_id_missing_field_is_none() -> None:
    assert extract_session_id({"type": "system", "subtype": "init"}) is None


def test_extract_session_id_non_str_field_is_none() -> None:
    assert extract_session_id(
        {"type": "system", "subtype": "init", "session_id": 123}
    ) is None


def test_extract_session_id_empty_str_is_none() -> None:
    assert extract_session_id(
        {"type": "system", "subtype": "init", "session_id": ""}
    ) is None


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


async def test_open_default_omits_resume_and_continue() -> None:
    # OFF path (BOB-087.D1): the default spawn carries NO --resume / --continue — the
    # live behaviour stays exactly BOB-083 (a fresh session) until D3/flags opt in.
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open("/work/dir", mode="acceptEdits")

    assert "--resume" not in spawner.calls[0]
    assert "--continue" not in spawner.calls[0]


async def test_open_resume_by_id_spawns_with_the_resume_argv() -> None:
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner, claude_bin="c")

    await runner.open("/w", mode="acceptEdits", resume_session_id="sess-7")

    assert spawner.calls[0][-2:] == ["--resume", "sess-7"]


async def test_open_continue_spawns_with_the_continue_argv() -> None:
    spawner = _FakeSpawner(_FakeProcess())
    runner = InteractiveClaudeRunner(spawner=spawner)

    await runner.open("/w", mode="acceptEdits", continue_session=True)

    assert spawner.calls[0][-1] == "--continue"


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


async def test_session_id_is_none_until_the_init_event_streams() -> None:
    proc = _FakeProcess(['{"type": "system", "subtype": "init", "session_id": "s-42"}\n'])
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")

    assert runner.session_id is None  # not seen yet

    await _collect(runner.events())

    # The claude-assigned id is captured off the stream so the manager can persist it
    # (BOB-087.D1) for a later --resume, without the transport owning session state.
    assert runner.session_id == "s-42"


async def test_session_id_stays_none_when_no_init_event_arrives() -> None:
    proc = _FakeProcess(['{"type": "assistant", "n": 1}\n'])
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(proc))
    await runner.open("/w", mode="plan")

    await _collect(runner.events())

    assert runner.session_id is None


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


async def test_events_before_open_yields_nothing() -> None:
    # No process spawned yet — the event stream is empty rather than crashing on a
    # ``None`` process (mirror of the feed/close before-open guards).
    runner = InteractiveClaudeRunner(spawner=_FakeSpawner(_FakeProcess(["ignored\n"])))

    assert await _collect(runner.events()) == []


def test_interactive_runner_satisfies_the_port() -> None:
    assert isinstance(InteractiveClaudeRunner(), InteractiveRunner)


# --------------------------------------------------------------------------- #
# The real exec transport: 64 KiB StreamReader limit (BOB-084 .1)
# --------------------------------------------------------------------------- #


class _RaisingStdout:
    """A stdout whose ``readline`` raises the overlong-line ``ValueError``.

    asyncio converts a ``StreamReader`` ``LimitOverrunError`` ("Separator is found, but
    chunk is longer than limit") into a ``ValueError`` — the exact crash a claude line
    past the buffer limit produces. This models the REAL transport failure the fake
    scripted-line process cannot reproduce.
    """

    async def readline(self) -> bytes:
        raise ValueError("Separator is found, but chunk is longer than limit")


class _FakeExecProc:
    """Minimal stand-in for ``asyncio.subprocess.Process`` with a raising stdout."""

    def __init__(self, stdout: _RaisingStdout) -> None:
        self.stdout = stdout
        self.stdin = None
        self.returncode: int | None = None


def _as_process(fake: _FakeExecProc) -> asyncio.subprocess.Process:
    # The adapter only touches ``.stdout`` here; cast so mypy accepts the minimal fake.
    return cast("asyncio.subprocess.Process", fake)


async def test_read_lines_ends_gracefully_on_an_overlong_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc = _ExecInteractiveProcess(_as_process(_FakeExecProc(_RaisingStdout())))

    with caplog.at_level(logging.WARNING):
        lines = [line async for line in proc.read_lines()]

    # No unhandled ValueError propagates to the pump; the stream ends as if at EOF.
    assert lines == []
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_spawner_passes_the_stream_limit_to_create_subprocess_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_exec(
        *argv: str, **kwargs: object
    ) -> asyncio.subprocess.Process:
        captured.update(kwargs)
        return _as_process(_FakeExecProc(_RaisingStdout()))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await _ExecInteractiveSpawner()(["claude", "-p"], cwd="/w")

    # The raised buffer limit is what keeps a >64 KiB claude line from crashing readline.
    assert captured["limit"] == _STREAM_LIMIT
    assert _STREAM_LIMIT == 16 * 1024 * 1024
