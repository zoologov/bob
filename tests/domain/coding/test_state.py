# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты машины состояний CodingSession (BOB-039 .1).

КЛЮЧЕВОЕ — гейт плана: EXECUTING достижимо ТОЛЬКО из PLAN_READY. Любой иной путь в
EXECUTING невалиден (двойной гейт непробиваем на уровне домена). Покрывают каждый
легальный переход, нелегальные (особенно обходы гейта), терминальность
DONE/CANCELLED/FAILED и чистые предикаты can_start/can_approve_plan/can_stop/
is_terminal.
"""

from __future__ import annotations

import pytest

from bob.domain.coding.state import (
    CodingSessionState,
    can_approve_plan,
    can_start,
    can_stop,
    can_transition,
    is_terminal,
)

_S = CodingSessionState


# --- Легальные переходы -------------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (_S.PROPOSED, _S.PLANNING),
        (_S.PLANNING, _S.PLAN_READY),
        (_S.PLAN_READY, _S.EXECUTING),  # гейт плана — единственный путь в EXECUTING
        (_S.EXECUTING, _S.PR_OPEN),
        # стоп/провал из любого нетерминального состояния
        (_S.PROPOSED, _S.CANCELLED),
        (_S.PLANNING, _S.CANCELLED),
        (_S.PLAN_READY, _S.CANCELLED),
        (_S.EXECUTING, _S.CANCELLED),
        (_S.PLANNING, _S.FAILED),
        (_S.EXECUTING, _S.FAILED),
    ],
)
def test_valid_transitions(frm: CodingSessionState, to: CodingSessionState) -> None:
    assert can_transition(frm, to) is True


# --- Гейт плана: EXECUTING только из PLAN_READY --------------------------------


@pytest.mark.parametrize(
    "frm",
    [
        _S.PROPOSED,
        _S.PLANNING,
        _S.EXECUTING,
        _S.PR_OPEN,
        _S.DONE,
        _S.CANCELLED,
        _S.FAILED,
    ],
)
def test_executing_unreachable_except_from_plan_ready(
    frm: CodingSessionState,
) -> None:
    # Непробиваемый двойной гейт: ни одно состояние, кроме PLAN_READY, не ведёт в
    # EXECUTING.
    assert can_transition(frm, _S.EXECUTING) is False


def test_only_plan_ready_reaches_executing() -> None:
    reaching = [
        s for s in CodingSessionState if can_transition(s, _S.EXECUTING)
    ]
    assert reaching == [_S.PLAN_READY]


# --- Нелегальные переходы -----------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (_S.PROPOSED, _S.PLAN_READY),  # нельзя миновать PLANNING
        (_S.PROPOSED, _S.PR_OPEN),
        (_S.PLANNING, _S.EXECUTING),  # нельзя миновать гейт плана
        (_S.PLAN_READY, _S.PR_OPEN),  # нельзя миновать EXECUTING
        (_S.PLAN_READY, _S.DONE),
        (_S.EXECUTING, _S.DONE),  # DONE только через PR_OPEN
    ],
)
def test_invalid_transitions(frm: CodingSessionState, to: CodingSessionState) -> None:
    assert can_transition(frm, to) is False


@pytest.mark.parametrize("state", [_S.PR_OPEN, _S.DONE, _S.CANCELLED, _S.FAILED])
def test_terminal_states_have_no_exits(state: CodingSessionState) -> None:
    assert is_terminal(state) is True
    for to in CodingSessionState:
        assert can_transition(state, to) is False


def test_pr_open_is_terminal_success() -> None:
    # BOB-042 Fix A: открыв PR, Боб закончил свою работу — мерж делает owner
    # асинхронно на GitHub, поэтому PR_OPEN — УСПЕШНЫЙ терминал. Это снимает
    # блокировку новой сессии (active() фильтрует терминальные).
    assert is_terminal(_S.PR_OPEN) is True
    # Гейт плана НЕ ослаблен: из PR_OPEN (он уже за гейтом) апрув невозможен.
    assert can_approve_plan(_S.PR_OPEN) is False


def test_same_state_is_not_a_transition() -> None:
    assert can_transition(_S.EXECUTING, _S.EXECUTING) is False


# --- Предикаты ----------------------------------------------------------------


def test_can_start_only_from_proposed() -> None:
    assert can_start(_S.PROPOSED) is True
    for state in CodingSessionState:
        if state is not _S.PROPOSED:
            assert can_start(state) is False


def test_can_approve_plan_only_from_plan_ready() -> None:
    # Гейт плана как предикат: апрув возможен ровно из PLAN_READY.
    assert can_approve_plan(_S.PLAN_READY) is True
    for state in CodingSessionState:
        if state is not _S.PLAN_READY:
            assert can_approve_plan(state) is False


def test_can_stop_from_any_non_terminal() -> None:
    for state in CodingSessionState:
        assert can_stop(state) is (not is_terminal(state))


def test_non_terminal_states_are_not_terminal() -> None:
    for state in (
        _S.PROPOSED,
        _S.PLANNING,
        _S.PLAN_READY,
        _S.EXECUTING,
    ):
        assert is_terminal(state) is False


def test_states_are_string_valued_for_persistence() -> None:
    assert _S.PLAN_READY.value == "plan_ready"
    assert _S.EXECUTING.value == "executing"
    assert _S.PR_OPEN.value == "pr_open"
