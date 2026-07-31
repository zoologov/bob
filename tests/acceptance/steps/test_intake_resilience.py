# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the intake-resilience acceptance scenarios (BOB-078 D).

Binds ``intake_resilience.feature`` to :mod:`tests.acceptance.intake_resilience_harness`,
which drives the two REAL loci of the fix: the coding session store's ``active()`` (skips a
broken row, returns the valid session) and ``PreComposeGate.maybe_route_coding`` (swallows a
router failure, does not consume the turn). The scenarios witness the resilience contract —
no throw, no lost turn — which is what keeps Bob answering after a corrupt session row.

Synchronous (pytest-bdd), so the async harness runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.intake_resilience_harness import (
    broken_session_lookup,
    coding_gate_consumed_the_turn,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/intake_resilience.feature")


@dataclass(slots=True)
class _ResilienceContext:
    """The slate the steps share across a scenario."""

    tmp_path: Path
    active_ids: tuple[str, ...] | None = None
    lookup_raised: bool = False
    consumed: bool | None = None
    gate_raised: bool = False


@pytest.fixture
def resilience_context(tmp_path: Path) -> _ResilienceContext:
    return _ResilienceContext(tmp_path=tmp_path)


# --- Scenario 1: the store lookup survives a broken row -----------------------


@given("в хранилище coding-сессий лежит битая строка рядом с валидной активной сессией")
def broken_row_seeded(resilience_context: _ResilienceContext) -> None:
    # The broken + valid rows are seeded inside the harness lookup (kept together with
    # the read so the scenario stays a single, self-contained turn).
    assert resilience_context.active_ids is None


@when("Боб ищет активную coding-сессию на входящем сообщении")
def bob_looks_up_active_session(resilience_context: _ResilienceContext) -> None:
    try:
        resilience_context.active_ids = asyncio.run(
            broken_session_lookup(resilience_context.tmp_path)
        )
    except Exception:
        resilience_context.lookup_raised = True


@then("поиск возвращает валидную сессию и не бросает исключение")
def lookup_returned_valid_session(resilience_context: _ResilienceContext) -> None:
    assert not resilience_context.lookup_raised, (
        "active() бросил на битой строке — intake-воркер бы упал, Боб оглох"
    )
    assert resilience_context.active_ids == ("live",), (
        "поиск не вернул валидную in-flight сессию (или подхватил битую строку)"
    )


# --- Scenario 2: the pre-compose gate swallows a router failure ---------------


@given("coding-роутер бросает ошибку на битой сессии")
def router_raises(resilience_context: _ResilienceContext) -> None:
    # The raising router is constructed inside the harness gate call.
    assert resilience_context.consumed is None


@when("владелец пишет Бобу, и pre-compose gate дёргает роутер")
def owner_writes_and_gate_routes(resilience_context: _ResilienceContext) -> None:
    try:
        resilience_context.consumed = asyncio.run(coding_gate_consumed_the_turn())
    except Exception:
        resilience_context.gate_raised = True


@then("gate не съедает ход и не крашит приём")
def gate_did_not_consume_or_crash(resilience_context: _ResilienceContext) -> None:
    assert not resilience_context.gate_raised, (
        "pre-compose gate пропустил ошибку роутера наружу — приём бы упал"
    )
    assert resilience_context.consumed is False, (
        "gate съел ход при упавшем роутере — ход потерян (Боб не ответил бы)"
    )
