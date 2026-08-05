# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the project-health scenarios (BOB-091.2).

Binds ``project_health.feature`` to :mod:`tests.acceptance.project_health_harness`, which
drives the REAL introspection adapter (only the subprocess is scripted, with the bytes
beadloom really prints), the REAL argv form gate, the REAL digest and the REAL tool-loop.
Every Then asserts an OBSERVABLE boundary value — the tool result fed to the model, the
argv that reached the subprocess, or the advertised manifest — never internals.

pytest-bdd scenarios are synchronous, so the async harness runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.project_health_harness import (
    ask_project_health,
    offered_tool_names,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/project_health.feature")

_HEALTH_TOOL = "project_health"

# Verbatim shapes of the live CLI in this repo (captured before implementation).
_SYNC_FRESH = "".join(
    f"  [ok] bob: architecture.md <-> src/bob/mod{index}.py\n" for index in range(40)
)
_SYNC_STALE = (
    "  [ok] bob: architecture.md <-> src/bob/one.py\n"
    "  [stale] bob: architecture.md <-> src/bob/capabilities/ports.py (hash_changed)\n"
)
_LINT_PORCELAIN = "some-rule:forbid_import:error:src/bob/two.py:2::\n"
_LINT_CLEAN = "0 violations, 224 rules evaluated\n"
_DIFF = (
    "Graph diff (since main):\n\nNodes:\n  + interactive (feature)\n\n"
    "1 added, 0 changed, 0 removed nodes; 1 added, 0 removed edges\n"
)
_PRIME = (
    "# Project: bob\n\nArchitecture: 3 domains, 2 services\n\n"
    "## Architecture Rules\n- domain-needs-parent (require): x\n- two (require): y\n\n"
    "## Domains\n- bob-domain: the domain layer\n"
)


@dataclass(slots=True)
class _Ctx:
    """The slate the steps share: the scripted stdout + the observed boundary values."""

    stdout: str = ""
    result: str = ""
    argv: list[list[str]] = field(default_factory=list)
    offered_tools: list[str] = field(default_factory=list)


@pytest.fixture
def ctx() -> _Ctx:
    return _Ctx()


def _ask(ctx: _Ctx, repo_root: Path, arguments: dict[str, object]) -> None:
    ctx.result, ctx.argv = asyncio.run(
        ask_project_health(repo_root, stdout=ctx.stdout, arguments=arguments)
    )


# --- Given --------------------------------------------------------------------


@given("beadloom печатает отчёт о свежести доков без устаревших пар")
def sync_check_is_fresh(ctx: _Ctx) -> None:
    ctx.stdout = _SYNC_FRESH


@given("beadloom печатает отчёт о свежести доков с устаревшей парой")
def sync_check_is_stale(ctx: _Ctx) -> None:
    ctx.stdout = _SYNC_STALE


@given("beadloom печатает нарушение границ машинным форматом")
def lint_reports_a_violation(ctx: _Ctx) -> None:
    ctx.stdout = _LINT_PORCELAIN


@given("beadloom печатает чистый вердикт по границам")
def lint_is_clean(ctx: _Ctx) -> None:
    ctx.stdout = _LINT_CLEAN


@given("beadloom печатает изменения графа")
def diff_reports_changes(ctx: _Ctx) -> None:
    ctx.stdout = _DIFF


@given("beadloom печатает компактный контекст проекта")
def prime_reports_context(ctx: _Ctx) -> None:
    ctx.stdout = _PRIME


@given("ход в разговоре")
def a_turn(ctx: _Ctx) -> None:
    assert ctx.result == ""


# --- When ---------------------------------------------------------------------


@when(parsers.parse('Боб смотрит отчёт "{check}"'))
def bob_looks_at_a_report(ctx: _Ctx, check: str, tmp_path: Path) -> None:
    _ask(ctx, tmp_path, {"check": check})


@when(parsers.parse('Боб просит отчёт "{check}"'))
def bob_asks_for_a_report(ctx: _Ctx, check: str, tmp_path: Path) -> None:
    _ask(ctx, tmp_path, {"check": check})


@when(parsers.parse('Боб смотрит отчёт "{check}" с момента "{since}"'))
def bob_looks_at_a_report_since(
    ctx: _Ctx, check: str, since: str, tmp_path: Path
) -> None:
    _ask(ctx, tmp_path, {"check": check, "since": since})


@when("инструменты собираются с выключенным флагом архитектуры")
def tools_built_with_flag_off(ctx: _Ctx) -> None:
    ctx.offered_tools = offered_tool_names(architecture_tools=False)


@when("инструменты собираются с включённым флагом архитектуры")
def tools_built_with_flag_on(ctx: _Ctx) -> None:
    ctx.offered_tools = offered_tool_names(architecture_tools=True)


# --- Then ---------------------------------------------------------------------


@then(parsers.parse('результат инструмента, ушедший модели, несёт "{fragment}"'))
def tool_result_carries(ctx: _Ctx, fragment: str) -> None:
    assert fragment in ctx.result, (
        f"реальный факт {fragment!r} не дошёл до модели: {ctx.result!r}"
    )


@then(parsers.parse('результата инструмента не несёт "{fragment}"'))
def tool_result_omits(ctx: _Ctx, fragment: str) -> None:
    assert fragment not in ctx.result, (
        f"{fragment!r} не должно доезжать до модели: {ctx.result!r}"
    )


@then(parsers.parse("в результате инструмента не больше {limit:d} строк"))
def tool_result_is_short(ctx: _Ctx, limit: int) -> None:
    lines = len(ctx.result.splitlines())
    assert lines <= limit, f"вместо вердикта пришёл дамп в {lines} строк"


@then("результат инструмента не выглядит отказом")
def tool_result_is_not_a_refusal(ctx: _Ctx) -> None:
    # 🔴 Ненулевой код возврата этих команд — РЕЗУЛЬТАТ, а не сбой: Боб отвечает
    # «доки отстали», а не «не смог посмотреть».
    lowered = ctx.result.lower()
    assert "не смог" not in lowered, f"вердикт превратился в отказ: {ctx.result!r}"
    assert "так нельзя" not in lowered, f"вердикт превратился в отказ: {ctx.result!r}"


@then("в результате инструмента нет машинных разделителей")
def tool_result_has_no_machine_separators(ctx: _Ctx) -> None:
    assert "::" not in ctx.result
    assert "forbid_import:error" not in ctx.result


@then(parsers.parse('в подпроцесс ушёл argv "{argv}"'))
def subprocess_got_argv(ctx: _Ctx, argv: str) -> None:
    assert ctx.argv == [argv.split(" ")], f"фактический argv: {ctx.argv!r}"


@then("в подпроцесс не ушло ничего")
def subprocess_ran_nothing(ctx: _Ctx) -> None:
    assert ctx.argv == [], f"команда всё-таки запустилась: {ctx.argv!r}"


@then("инструмент состояния проекта не предлагается")
def health_tool_absent(ctx: _Ctx) -> None:
    assert _HEALTH_TOOL not in ctx.offered_tools, (
        f"{_HEALTH_TOOL} предложен при выключенном флаге"
    )


@then("инструмент состояния проекта предлагается")
def health_tool_present(ctx: _Ctx) -> None:
    assert _HEALTH_TOOL in ctx.offered_tools
