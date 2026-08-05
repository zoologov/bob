# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the autobiographical-memory scenarios (BOB-079).

Binds ``self_action_autobiography.feature`` to
:mod:`tests.acceptance.self_action_autobio_harness`, which records a self-action with the
REAL recorder into a REAL SQLite store, answers a relevant question via the REAL keyword
recall, runs the REAL read gates, and folds the REAL ownership voice directive. The
scenarios assert Bob's OBSERVABLE framing — which first-person deed grounds the reply and
whether the ownership directive is active — through that composed-reply boundary, never
the store/loop internals.

The scenarios are synchronous (pytest-bdd), so the async read path runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.memory.self_action import SelfAction, SelfActionKind
from tests.acceptance.self_action_autobio_harness import (
    OwnershipOutcome,
    recall_own_deeds,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/self_action_autobiography.feature")


@dataclass(slots=True)
class _AutobioContext:
    """The slate the steps share: isolated store root, deeds to record, the outcome."""

    tmp_path: Path
    to_record: list[SelfAction] = field(default_factory=list)
    outcome: OwnershipOutcome = field(default_factory=OwnershipOutcome)


@pytest.fixture
def autobio_context(tmp_path: Path) -> _AutobioContext:
    """A fresh, isolated SQLite store per scenario."""
    return _AutobioContext(tmp_path=tmp_path)


# --- Given: what Bob did (or didn't) --------------------------------------------


@given("Боб записал своё действие: он залип в кодере и флудил правками")
def bob_recorded_a_runaway(autobio_context: _AutobioContext) -> None:
    autobio_context.to_record.append(
        SelfAction(kind=SelfActionKind.CODING_RUNAWAY, target="BOB-076")
    )


@given(
    "Боб записал своё действие: он воспользовался инструментами read_code и list_dir"
)
def bob_recorded_a_tool_use(autobio_context: _AutobioContext) -> None:
    autobio_context.to_record.append(
        SelfAction(kind=SelfActionKind.TOOL_USE, target="read_code, list_dir")
    )


@given("Боб записал своё действие: он довёл работу до ветки в форке и отдал ссылку на PR")
def bob_recorded_a_fork_handoff(autobio_context: _AutobioContext) -> None:
    # Форк-путь BOB-089: PR открывает владелец по ссылке, поэтому поступок Боба — ДРУГОЙ.
    autobio_context.to_record.append(
        SelfAction(kind=SelfActionKind.CODING_HANDED_OFF, target="BOB-089")
    )


@given("Боб НЕ записывал никакого своего действия")
def bob_recorded_nothing(autobio_context: _AutobioContext) -> None:
    assert autobio_context.to_record == []


# --- When: the owner asks something relevant ------------------------------------


@when("владелец спрашивает «помнишь тот инцидент с кодером?»")
def owner_asks_about_the_incident(autobio_context: _AutobioContext) -> None:
    _drive(autobio_context, "помнишь тот инцидент с кодером, когда ты залип?")


@when("владелец спрашивает, какими инструментами Боб сегодня пользовался")
def owner_asks_about_tools(autobio_context: _AutobioContext) -> None:
    _drive(autobio_context, "какими инструментами ты сегодня пользовался?")


@when("владелец спрашивает «ты открыл PR по BOB-089?»")
def owner_asks_whether_bob_opened_the_pr(autobio_context: _AutobioContext) -> None:
    _drive(autobio_context, "ты открыл PR по BOB-089?")


def _drive(context: _AutobioContext, question: str) -> None:
    context.outcome = asyncio.run(
        recall_own_deeds(context.tmp_path, question, record=context.to_record)
    )


# --- Then: Bob's observable framing ---------------------------------------------


@then('всплывает поступок Боба от первого лица «я залип … флудил правками»')
def runaway_deed_surfaces_first_person(autobio_context: _AutobioContext) -> None:
    surfaced = " | ".join(autobio_context.outcome.surfaced)
    assert "я залип" in surfaced, (
        f"свой сбой не всплыл от первого лица; всплыло: {surfaced!r}"
    )
    assert "флудил правками" in surfaced


@then('всплывает поступок Боба от первого лица «я воспользовался инструментами»')
def tool_use_deed_surfaces_first_person(autobio_context: _AutobioContext) -> None:
    surfaced = " | ".join(autobio_context.outcome.surfaced)
    assert "я воспользовался инструментами" in surfaced, (
        f"своё действие не всплыло от первого лица; всплыло: {surfaced!r}"
    )
    assert "read_code" in surfaced


@then('всплывает поступок Боба от первого лица «я довёл … до ветки в своём форке»')
def fork_handoff_deed_surfaces_first_person(autobio_context: _AutobioContext) -> None:
    surfaced = " | ".join(autobio_context.outcome.surfaced)
    assert "я довёл" in surfaced, (
        f"передача работы не всплыла от первого лица; всплыло: {surfaced!r}"
    )
    assert "в своём форке" in surfaced


@then("во всплывшем поступке нет заявления об открытом PR")
def surfaced_deed_claims_no_opened_pr(autobio_context: _AutobioContext) -> None:
    surfaced = " | ".join(autobio_context.outcome.surfaced)
    # 🔴 Именно этот текст ложится в основу ответа Боба о себе: заявление о чужом нажатии
    # здесь и есть конфабуляция «я это помню, я сам так сделал».
    assert "открыл PR" not in surfaced, (
        f"Боб присвоил себе открытие PR, которого не открывал: {surfaced!r}"
    )
    assert "PR открыт" not in surfaced


@then(
    "включается директива присвоения — говорить о поступке как о своём, "
    "честно признать промах"
)
def ownership_directive_is_active(autobio_context: _AutobioContext) -> None:
    outcome = autobio_context.outcome
    assert outcome.ownership_directive_active, (
        "директива присвоения не включилась, хотя свой поступок всплыл"
    )
    folded = outcome.directive.casefold()
    assert "от первого лица" in folded
    assert "не выдумывай" in folded  # INV-3: honesty без конфабуляции


@then("никакой поступок Боба не всплывает")
def no_deed_surfaces(autobio_context: _AutobioContext) -> None:
    assert autobio_context.outcome.surfaced == (), (
        f"поступок всплыл, хотя ничего не записывалось: {autobio_context.outcome.surfaced!r}"
    )


@then(
    "директива присвоения НЕ включается — присваивать нечего, "
    "выдумывать поступок нельзя"
)
def ownership_directive_is_absent(autobio_context: _AutobioContext) -> None:
    outcome = autobio_context.outcome
    assert outcome.ownership_directive_active is False, (
        "директива присвоения включилась без записанного поступка (риск конфабуляции)"
    )
    assert outcome.directive == ""
