# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the anti-narration backstop scenario (BOB-074).

Binds ``tool_narration_backstop.feature`` to :mod:`tests.acceptance.tool_narration_harness`,
which drives the REAL ToolLoop over a REAL ``read_code`` capability while a scripted provider
NARRATES GUPPI's intent on turn 1 (no tool call). The scenario asserts Bob's OBSERVABLE final
reply — it carries the real fact read from the file and drops the intent narration — plus the
one boundary-visible effect of the backstop: the hard nudge reached the model before its retry.

The scenario is synchronous (pytest-bdd), so the async loop runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.tool_narration_harness import REAL_FACT, run_narration_backstop

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/tool_narration_backstop.feature")


@dataclass(slots=True)
class _NarrationContext:
    """The slate the steps share: temp repo root, final reply, nudge-reached flag."""

    tmp_path: Path
    reply: str = ""
    retry_saw_nudge: bool = False


@pytest.fixture
def narration_context(tmp_path: Path) -> _NarrationContext:
    """A fresh, isolated repo tree per scenario."""
    return _NarrationContext(tmp_path=tmp_path)


@given("владелец просит Боба заглянуть в файл, а контекст отравлен нарративом")
def owner_asks_with_poisoned_context(narration_context: _NarrationContext) -> None:
    """A clean slate — the poisoned turn is scripted inside the harness."""
    assert narration_context.reply == ""


@when("Боб проходит инструмент-петлю до финального ответа")
def bob_runs_the_tool_loop(narration_context: _NarrationContext) -> None:
    reply, retry_saw_nudge = asyncio.run(
        run_narration_backstop(narration_context.tmp_path)
    )
    narration_context.reply = reply
    narration_context.retry_saw_nudge = retry_saw_nudge


@then("страховка переспросила модель жёстким нюджем")
def backstop_re_asked_with_nudge(narration_context: _NarrationContext) -> None:
    assert narration_context.retry_saw_nudge, (
        "страховка не переспросила модель — жёсткий нюдж не дошёл до ретрая"
    )


@then("в ответе есть реальный факт из файла")
def reply_has_real_fact(narration_context: _NarrationContext) -> None:
    assert REAL_FACT in narration_context.reply, (
        "финальный ответ не несёт факт из файла — страховка не дожала реальный вызов"
    )


@then("в ответе нет нарратива о намерении GUPPI")
def reply_has_no_intent_narration(narration_context: _NarrationContext) -> None:
    lowered = narration_context.reply.lower()
    assert "ждём отчёт" not in lowered, "нарратив о намерении утёк в чат"
    assert "уже пошёл" not in lowered, "нарратив о намерении утёк в чат"
