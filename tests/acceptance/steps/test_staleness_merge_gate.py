# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the staleness/merge-gate acceptance scenarios (BOB-066 3.1).

Binds the Gherkin of ``staleness_merge_gate.feature`` to
:mod:`tests.acceptance.staleness_harness`: a drafted reply whose point was answered by
someone else during generation DROPS_TO_LIKE (a reaction, not a duplicate reply), and a
same-author follow-up question MERGES both into one deduplicated reply. The scenarios
are synchronous (pytest-bdd), so the async reassess contract is driven via
``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.staleness_harness import (
    DRAFT_AUTHOR_ID,
    OTHER_ID,
    reassess_outcome,
)

scenarios("../features/staleness_merge_gate.feature")


@dataclass(slots=True)
class StalenessScenarioContext:
    """The slate the staleness scenario's steps share."""

    outcome: str | None = None


@pytest.fixture
def staleness_context() -> StalenessScenarioContext:
    return StalenessScenarioContext()


@given("Боб дописал ответ, пока в чат что-то приходило")
def bob_drafted_while_messages_arrived(
    staleness_context: StalenessScenarioContext,
) -> None:
    # Readiness — the outcome is produced in the When step.
    assert staleness_context.outcome is None


@when("другой участник уже ответил на тот же вопрос")
def another_answered_the_same_question(
    staleness_context: StalenessScenarioContext,
) -> None:
    staleness_context.outcome = asyncio.run(
        reassess_outcome(answered_by_other=True, arrival_author_id=OTHER_ID)
    )


@when("автор вопроса тут же дописал новый прямой вопрос")
def author_added_a_new_direct_question(
    staleness_context: StalenessScenarioContext,
) -> None:
    staleness_context.outcome = asyncio.run(
        reassess_outcome(
            same_author_clarified=True,
            new_direct_question=True,
            arrival_author_id=DRAFT_AUTHOR_ID,
        )
    )


@then("Боб не выстреливает дубль, а ставит реакцию")
def bob_drops_to_like(staleness_context: StalenessScenarioContext) -> None:
    assert staleness_context.outcome == "drop_to_like", (
        "Боб выстрелил устаревший дубль вместо реакции"
    )


@then("Боб сливает всё в один ответ")
def bob_merges(staleness_context: StalenessScenarioContext) -> None:
    assert staleness_context.outcome == "merge", (
        "Боб не слил новый вопрос в один ответ"
    )
