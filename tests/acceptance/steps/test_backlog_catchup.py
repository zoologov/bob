# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the backlog catch-up acceptance scenarios (BOB-066 3.2).

Binds the Gherkin of ``backlog_catchup.feature`` to :mod:`tests.acceptance.catchup_harness`:
one re-entry pass over a backlog with a direct question amid many ambient asides answers the
direct question and does NOT reply to every ambient, and — the load-bearing INV-1/INV-10
guarantee — every direct address survives even when the budget is smaller than the number
of direct addresses (only ambient periphery collapses).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.catchup_harness import (
    BacklogBuilder,
    run_catchup,
    run_catchup_collapsed,
)

scenarios("../features/backlog_catchup.feature")

_BUDGET = 2


@dataclass(slots=True)
class CatchUpScenarioContext:
    """The slate the catch-up scenario's steps share."""

    builder: BacklogBuilder = field(default_factory=BacklogBuilder)
    answered: list[str] = field(default_factory=list)
    collapsed: list[str] = field(default_factory=list)
    direct_texts: list[str] = field(default_factory=list)


@pytest.fixture
def catchup_context() -> CatchUpScenarioContext:
    return CatchUpScenarioContext()


@given("Боб вернулся к чату, где накопился завал")
def bob_returned_to_a_backlog(catchup_context: CatchUpScenarioContext) -> None:
    # Readiness — the backlog is populated in the following steps.
    assert not catchup_context.builder.messages


@given("в завале один прямой вопрос к Бобу и много фоновой болтовни")
def one_direct_many_ambient(catchup_context: CatchUpScenarioContext) -> None:
    catchup_context.builder.add_direct_question("Боб, ты тут?")
    catchup_context.direct_texts.append("Боб, ты тут?")
    for i in range(6):
        catchup_context.builder.add_ambient(f"болтовня-{i}", age_hours=float(i + 1))


@given("в завале несколько прямых обращений к Бобу — больше, чем бюджет")
def several_direct_over_budget(catchup_context: CatchUpScenarioContext) -> None:
    for i in range(_BUDGET + 2):
        text = f"Боб, вопрос {i}?"
        catchup_context.builder.add_direct_question(text)
        catchup_context.direct_texts.append(text)
    catchup_context.builder.add_ambient("фоновая болтовня", age_hours=1.0)


@when("Боб одним проходом разбирает backlog с ограниченным бюджетом")
def bob_runs_one_pass(catchup_context: CatchUpScenarioContext) -> None:
    backlog = tuple(catchup_context.builder.messages)
    catchup_context.answered = run_catchup(backlog, budget=_BUDGET)
    catchup_context.collapsed = run_catchup_collapsed(backlog, budget=_BUDGET)


@then("Боб отвечает на прямой вопрос")
def bob_answers_the_direct_question(catchup_context: CatchUpScenarioContext) -> None:
    assert "Боб, ты тут?" in catchup_context.answered, (
        "Боб потерял прямой вопрос в шуме backlog"
    )


@then("Боб не отвечает на каждую фоновую реплику")
def bob_does_not_answer_every_ambient(
    catchup_context: CatchUpScenarioContext,
) -> None:
    assert catchup_context.collapsed, (
        "Боб ответил на всю фоновую болтовню вместо одного прохода с бюджетом"
    )
    # A budget of two, one focal → at most one ambient rides along; the rest collapse.
    ambient_answered = [
        text for text in catchup_context.answered if text.startswith("болтовня")
    ]
    assert len(ambient_answered) <= _BUDGET - 1


@then("Боб отвечает на все прямые обращения")
def bob_answers_every_direct(catchup_context: CatchUpScenarioContext) -> None:
    for text in catchup_context.direct_texts:
        assert text in catchup_context.answered, (
            f"Боб потерял прямое обращение «{text}» при исчерпанном бюджете"
        )


@then("схлопывается только фоновая периферия")
def only_ambient_collapses(catchup_context: CatchUpScenarioContext) -> None:
    assert catchup_context.collapsed == ["фоновая болтовня"], (
        "Схлопнулось не только фоновое — фокус не должен теряться"
    )
