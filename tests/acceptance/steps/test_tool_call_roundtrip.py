# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the tool-call round-trip scenario (BOB-069.B).

Binds ``tool_call_roundtrip.feature`` to :mod:`tests.acceptance.tool_roundtrip_harness`,
which drives the REAL ToolLoop over a REAL ``read_code`` capability while the provider
parses canned wire bodies through the REAL openai_compat parser — including a turn that
reproduces the live Qwen echo bug. The scenario asserts Bob's OBSERVABLE final reply: it
carries a real fact read from the file and never the raw ``[tool_calls]`` marker.

The scenario is synchronous (pytest-bdd), so the async loop runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.tool_roundtrip_harness import (
    REAL_FACT,
    TOOL_CALLS_MARKER,
    run_tool_roundtrip,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/tool_call_roundtrip.feature")


@dataclass(slots=True)
class _ToolContext:
    """The slate the tool-loop steps share: temp repo root + the final reply text."""

    tmp_path: Path
    reply: str = ""


@pytest.fixture
def tool_context(tmp_path: Path) -> _ToolContext:
    """A fresh, isolated repo tree per scenario."""
    return _ToolContext(tmp_path=tmp_path)


@given("владелец просит Боба заглянуть в файл репозитория")
def owner_asks_to_read(tool_context: _ToolContext) -> None:
    """A clean slate — the request is embedded in the harness's seeded turn."""
    assert tool_context.reply == ""


@when("Боб проходит инструмент-петлю до финального ответа")
def bob_runs_the_tool_loop(tool_context: _ToolContext) -> None:
    tool_context.reply = asyncio.run(run_tool_roundtrip(tool_context.tmp_path))


@then("в ответе есть реальный факт из файла")
def reply_has_real_fact(tool_context: _ToolContext) -> None:
    assert REAL_FACT in tool_context.reply, (
        "финальный ответ не несёт факт из файла — петля не сомкнулась в текст"
    )


@then('в ответе нет сырой строки вызова "[tool_calls]"')
def reply_has_no_tool_call_leak(tool_context: _ToolContext) -> None:
    assert TOOL_CALLS_MARKER not in tool_context.reply, (
        "сырая строка [tool_calls] утекла в чат вместо выполнения инструмента"
    )
