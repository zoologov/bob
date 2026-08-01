# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the dev-introspection scenarios (BOB-081.3).

Binds ``dev_introspection.feature`` to :mod:`tests.acceptance.dev_introspection_harness`,
which drives the REAL tool-loop over the REAL dev tools + a scripted fake port (S1–S5a),
and the REAL VoiceComposer guest gate (S5b). Every Then asserts an OBSERVABLE boundary
value — the tool result fed to the model, or whether the tool-loop ran — never internals.

pytest-bdd scenarios are synchronous, so the async harness runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.dev_introspection_harness import compose_turn, run_dev_tool
from tests.application.capabilities.fakes import FakeRepoIntrospector

scenarios("../features/dev_introspection.feature")


@dataclass(slots=True)
class _Ctx:
    """The slate the steps share: the scripted port + the observed boundary values."""

    introspector: FakeRepoIntrospector = field(default_factory=FakeRepoIntrospector)
    result: str = ""
    tool_loop_calls: int = 0
    offered_tools: list[str] = field(default_factory=list)


@pytest.fixture
def ctx() -> _Ctx:
    return _Ctx()


# --- Given --------------------------------------------------------------------


@given(parsers.parse('git-история содержит коммит "{commit}"'))
def history_has_commit(ctx: _Ctx, commit: str) -> None:
    ctx.introspector = FakeRepoIntrospector(commits=f"abc1234 {commit}")


@given("git-история пуста")
def history_is_empty(ctx: _Ctx) -> None:
    ctx.introspector = FakeRepoIntrospector(commits="")


@given(parsers.parse('в трекере есть закрытая задача "{task}"'))
def tracker_has_closed_task(ctx: _Ctx, task: str) -> None:
    ctx.introspector = FakeRepoIntrospector(tasks_by_status_text=f"✓ {task}")


@given(parsers.parse('у задачи "{bead}" есть детали "{detail}"'))
def task_has_detail(ctx: _Ctx, bead: str, detail: str) -> None:
    ctx.introspector = FakeRepoIntrospector(task_detail=f"{bead}: {detail}")


@given(parsers.parse('у задачи "{bead}" есть комментарий "{comment}"'))
def task_has_comment(ctx: _Ctx, bead: str, comment: str) -> None:
    ctx.introspector = FakeRepoIntrospector(comments=comment)


@given("ход в разговоре")
def a_turn(ctx: _Ctx) -> None:
    assert ctx.result == ""


# --- When ---------------------------------------------------------------------


@when("Боб вызывает инструмент последних коммитов")
def bob_calls_recent_commits(ctx: _Ctx) -> None:
    ctx.result = asyncio.run(
        run_dev_tool(ctx.introspector, tool="recent_commits", arguments={"count": 10})
    )


@when(parsers.parse('Боб вызывает инструмент задач со статусом "{status}"'))
def bob_calls_list_tasks(ctx: _Ctx, status: str) -> None:
    ctx.result = asyncio.run(
        run_dev_tool(ctx.introspector, tool="list_tasks", arguments={"status": status})
    )


@when(parsers.parse('Боб вызывает инструмент деталей задачи "{bead}"'))
def bob_calls_show_task(ctx: _Ctx, bead: str) -> None:
    ctx.result = asyncio.run(
        run_dev_tool(ctx.introspector, tool="show_task", arguments={"id": bead})
    )


@when(parsers.parse('Боб вызывает инструмент комментариев задачи "{bead}"'))
def bob_calls_task_comments(ctx: _Ctx, bead: str) -> None:
    ctx.result = asyncio.run(
        run_dev_tool(ctx.introspector, tool="task_comments", arguments={"id": bead})
    )


@when("ход обрабатывается как гостевой")
def turn_processed_as_guest(ctx: _Ctx) -> None:
    ctx.tool_loop_calls, ctx.offered_tools = asyncio.run(compose_turn(is_guest=True))


@when("ход обрабатывается как авторизованный")
def turn_processed_as_authorized(ctx: _Ctx) -> None:
    ctx.tool_loop_calls, ctx.offered_tools = asyncio.run(compose_turn(is_guest=False))


# --- Then ---------------------------------------------------------------------


@then(parsers.parse('результат инструмента, ушедший модели, несёт "{fragment}"'))
def tool_result_carries(ctx: _Ctx, fragment: str) -> None:
    assert fragment in ctx.result, (
        f"реальный факт {fragment!r} не дошёл до модели: {ctx.result!r}"
    )


@then(parsers.parse('в трекер ушёл запрос статуса "{status}"'))
def tracker_got_status(ctx: _Ctx, status: str) -> None:
    assert ctx.introspector.tasks_by_status_calls == [status]


@then("результат инструмента, ушедший модели, честно сообщает «не нашёл»")
def tool_result_is_honestly_empty(ctx: _Ctx) -> None:
    lowered = ctx.result.lower()
    assert "не наш" in lowered, f"пустая история должна честно сообщить: {ctx.result!r}"
    assert "abc" not in lowered, "пустой результат не должен фабриковать коммит"


@then("инструмент-петля не запускается и инструменты не предлагаются")
def guest_gets_no_tools(ctx: _Ctx) -> None:
    assert ctx.tool_loop_calls == 0, "гостю запустили инструмент-петлю (нарушен INV-4)"
    assert ctx.offered_tools == [], "гостю предложили инструменты"


@then("инструмент-петля запускается и dev-инструменты предлагаются")
def authorized_gets_tools(ctx: _Ctx) -> None:
    assert ctx.tool_loop_calls == 1, "авторизованному ходу не запустили инструмент-петлю"
    assert "recent_commits" in ctx.offered_tools
    assert "list_tasks" in ctx.offered_tools
