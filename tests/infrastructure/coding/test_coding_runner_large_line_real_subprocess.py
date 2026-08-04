# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-subprocess regression net for BOB-084 — a stream-json line >64 KiB.

The whole point of this file: the unit suites (``test_claude_runner.py`` /
``test_interactive_runner.py``) drive an INJECTED fake process with scripted short
lines, so they can never reproduce the ORIGINAL crash — the 64 KiB
``StreamReader`` buffer limit is a property of the *real* subprocess transport that
the fakes do not model (the "fakes don't reproduce a real-transport limit" lesson,
BOB-067). asyncio's ``create_subprocess_exec`` gives its ``StreamReader`` a DEFAULT
64 KiB limit; before the fix, ``readline()`` on a longer ``stream-json`` line raised
``LimitOverrunError`` (surfaced as ``ValueError``) and killed the output pump → the
interactive session died on claude's first big event ("открылось и сдохло").

The fix (bead .1) passes ``limit=_STREAM_LIMIT`` (16 MiB) to BOTH default spawners
and makes ``read_lines`` end gracefully on a ``ValueError``. These tests exercise the
runners' OWN default spawner (``_ExecStreamRunner`` / ``_ExecInteractiveSpawner``) —
NOT the injected fake — by standing a tiny real child process in for ``claude`` that
prints ONE ~200 KiB stream-json line (well over the OLD 64 KiB limit, well under the
new 16 MiB one). Against pre-fix code this reproduces the crash; against the fix both
runners read the event and complete, and the child is reaped (no zombie).

POSIX-only (a shebang stands the helper in for the ``claude`` binary), matching the
other real-tool integration tests in this package (real ``git`` / ``bd`` / ``beadloom``).
"""

from __future__ import annotations

import stat
import sys
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.claude_runner import SubprocessClaudeRunner
from bob.interactive.adapters.runner import InteractiveClaudeRunner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        sys.platform.startswith("win"),
        reason="shebang helper stands in for the claude binary (POSIX only)",
    ),
]

# asyncio's ``StreamReader`` DEFAULT limit — the buffer size that made the original
# ``readline()`` raise ``LimitOverrunError`` on a longer line (the shipped bug).
_OLD_ASYNCIO_LIMIT = 64 * 1024

# The child emits ONE line this many ``a``s wide: > 64 KiB (old limit → old crash),
# < 16 MiB (``_STREAM_LIMIT`` → the fix reads it). This IS the production scenario
# (a big tool-result / file-read / long assistant message), kept to one short line so
# the real-subprocess test stays fast.
_LINE_LEN = 200_000


def _write_big_line_helper(tmp_path: Path) -> str:
    """Create an executable helper that stands in for ``claude``.

    It ignores every argv the runner appends (``-p``/flags) and prints ONE valid
    ``stream-json`` line of ~200 KiB to stdout, then exits (EOF). Returned as a path
    so the runner's DEFAULT spawner launches it as a REAL child — the actual
    ``create_subprocess_exec`` + ``StreamReader.readline()`` transport under test.
    """
    script = tmp_path / "fake_claude.py"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f'_line = \'{{"type": "assistant", "x": "\' + "a" * {_LINE_LEN} + \'"}}\'\n'
        'sys.stdout.write(_line + "\\n")\n'
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


async def _collect(events: AsyncIterator[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [event async for event in events]


def _assert_big_assistant_event(events: list[Mapping[str, object]]) -> None:
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "assistant"
    payload = event["x"]
    assert isinstance(payload, str)
    assert len(payload) == _LINE_LEN
    # Sanity: the line is genuinely past the OLD 64 KiB asyncio default — i.e. this is
    # exactly the input that crashed pre-fix code with LimitOverrunError/ValueError.
    assert len(payload) > _OLD_ASYNCIO_LIMIT


async def test_subprocess_runner_reads_stream_json_line_over_64kib_via_real_child(
    tmp_path: Path,
) -> None:
    # Arrange: a REAL child (the runner's own _ExecStreamRunner, no injected fake).
    claude_bin = _write_big_line_helper(tmp_path)
    runner = SubprocessClaudeRunner(claude_bin=claude_bin)

    # Act: fully consume the stream — readline() must cross the 64 KiB boundary.
    events = await _collect(runner.run(str(tmp_path), "task", mode="plan"))

    # Assert: the >64 KiB event was read WITHOUT LimitOverrunError; run()'s finally
    # reaped the child (no zombie).
    _assert_big_assistant_event(events)


async def test_interactive_runner_reads_stream_json_line_over_64kib_via_real_child(
    tmp_path: Path,
) -> None:
    # Arrange: a REAL persistent child via the default _ExecInteractiveSpawner.
    claude_bin = _write_big_line_helper(tmp_path)
    runner = InteractiveClaudeRunner(claude_bin=claude_bin)
    await runner.open(str(tmp_path), mode="plan")

    # Act: read the stdout stream to EOF; then close() must terminate + reap.
    try:
        events = await _collect(runner.events())
    finally:
        await runner.close()

    # Assert: the >64 KiB event surfaced without crashing the pump; close() is
    # idempotent (child already reaped — a second close is a no-op, no zombie).
    _assert_big_assistant_event(events)
    await runner.close()
