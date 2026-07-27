# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты машины состояний цели/задачи (BOB-015 .1).

Покрывают валидные/невалидные переходы ``GoalState`` (КЛЮЧЕВОЕ: PROPOSED→APPROVED
валиден — его инициирует owner-апрув на уровне use-case в .2) и ``TaskState``, плюс
immutable-инварианты доменных дата-классов ``Goal`` / ``Task``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from bob.proactivity.goals.entities import Goal, GoalOrigin, Task
from bob.proactivity.goals.state import (
    GoalState,
    TaskState,
    can_transition,
    can_transition_task,
)

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _goal(state: GoalState = GoalState.PROPOSED) -> Goal:
    return Goal(
        id="g1",
        title="Выучить рекурсию",
        description="Разобраться в рекурсии до автоматизма",
        priority=2,
        criteria="Могу объяснить и применить",
        state=state,
        created_at=_NOW,
        origin=GoalOrigin.OWNER,
    )


# --- GoalState machine --------------------------------------------------------


def test_proposed_to_approved_is_valid() -> None:
    # КЛЮЧЕВОЕ: owner-апрув переводит PROPOSED -> APPROVED (инициирует use-case в .2).
    assert can_transition(GoalState.PROPOSED, GoalState.APPROVED) is True


def test_approved_to_active_is_valid() -> None:
    assert can_transition(GoalState.APPROVED, GoalState.ACTIVE) is True


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (GoalState.ACTIVE, GoalState.BLOCKED),
        (GoalState.BLOCKED, GoalState.ACTIVE),
        (GoalState.ACTIVE, GoalState.DONE),
        (GoalState.ACTIVE, GoalState.PAUSED),
        (GoalState.PAUSED, GoalState.ACTIVE),
        (GoalState.ACTIVE, GoalState.CANCELLED),
        (GoalState.PROPOSED, GoalState.CANCELLED),
    ],
)
def test_valid_goal_transitions(frm: GoalState, to: GoalState) -> None:
    assert can_transition(frm, to) is True


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (GoalState.PROPOSED, GoalState.ACTIVE),  # нельзя миновать APPROVED
        (GoalState.PROPOSED, GoalState.DONE),
        (GoalState.DONE, GoalState.ACTIVE),  # терминальное
        (GoalState.CANCELLED, GoalState.APPROVED),  # терминальное
        (GoalState.APPROVED, GoalState.DONE),  # без прохождения ACTIVE
    ],
)
def test_invalid_goal_transitions(frm: GoalState, to: GoalState) -> None:
    assert can_transition(frm, to) is False


def test_same_state_is_not_a_transition() -> None:
    assert can_transition(GoalState.ACTIVE, GoalState.ACTIVE) is False


# --- TaskState machine --------------------------------------------------------


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (TaskState.NEW, TaskState.READY),
        (TaskState.READY, TaskState.IN_PROGRESS),
        (TaskState.IN_PROGRESS, TaskState.DONE),
        (TaskState.IN_PROGRESS, TaskState.BLOCKED),
        (TaskState.BLOCKED, TaskState.READY),
        (TaskState.NEW, TaskState.SKIPPED),
        (TaskState.READY, TaskState.BLOCKED),
    ],
)
def test_valid_task_transitions(frm: TaskState, to: TaskState) -> None:
    assert can_transition_task(frm, to) is True


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (TaskState.NEW, TaskState.DONE),  # нельзя миновать READY/IN_PROGRESS
        (TaskState.DONE, TaskState.READY),  # терминальное
        (TaskState.SKIPPED, TaskState.READY),  # терминальное
    ],
)
def test_invalid_task_transitions(frm: TaskState, to: TaskState) -> None:
    assert can_transition_task(frm, to) is False


# --- Immutable-инварианты дата-классов ----------------------------------------


def test_goal_is_frozen() -> None:
    goal = _goal()
    with pytest.raises(dataclasses.FrozenInstanceError):
        goal.state = GoalState.APPROVED  # type: ignore[misc]


def test_task_is_frozen() -> None:
    task = Task(
        id="t1",
        goal_id="g1",
        summary="Прочитать главу",
        deps=(),
        state=TaskState.NEW,
        needs_external_agency=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        task.state = TaskState.DONE  # type: ignore[misc]


def test_goal_carries_origin_and_optional_deadline() -> None:
    goal = _goal()
    assert goal.origin is GoalOrigin.OWNER
    assert goal.deadline is None


def test_enums_are_string_valued_for_persistence() -> None:
    # Строковые значения упрощают round-trip в SQLite (TEXT-колонки).
    assert GoalState.APPROVED.value == "approved"
    assert TaskState.IN_PROGRESS.value == "in_progress"
    assert GoalOrigin.BOB_PROPOSED.value == "bob_proposed"
