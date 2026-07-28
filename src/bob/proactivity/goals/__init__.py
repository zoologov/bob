# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Goal Engine — чистый граф целей Боба (без I/O, детерминированно; BOB-015).

Подложка автономности-стадии B: цели (:class:`Goal`) и их задачи (:class:`Task`)
как immutable value-objects, машины состояний (:class:`GoalState` /
:class:`TaskState` + чистые предикаты переходов) и :class:`GoalGraph` с граф-
функциями готовности/выбора (:func:`ready_tasks`, :func:`next_safe_task`,
:func:`is_goal_complete`, :func:`blocked_reason`, :func:`external_agency_tasks`).

Authz-before-autonomy зашит структурно: к авто-продвижению допущены только цели в
``APPROVED`` / ``ACTIVE``, а внешне-агентные задачи (``needs_external_agency``)
исключены из авто-готовых и лишь помечаются для предложения owner. Персист — за
портом :class:`bob.proactivity.ports.GoalStore` (адаптер ``SqliteGoalStore`` в
infrastructure); Planner (.2) и самонаправленный тик (.3) строятся поверх.
"""

from __future__ import annotations

from bob.proactivity.goals.entities import Goal, GoalOrigin, Task
from bob.proactivity.goals.graph import (
    GoalGraph,
    blocked_reason,
    external_agency_tasks,
    is_goal_complete,
    next_safe_task,
    ready_tasks,
)
from bob.proactivity.goals.state import (
    GoalState,
    TaskState,
    can_transition,
    can_transition_task,
)

__all__ = [
    "Goal",
    "GoalGraph",
    "GoalOrigin",
    "GoalState",
    "Task",
    "TaskState",
    "blocked_reason",
    "can_transition",
    "can_transition_task",
    "external_agency_tasks",
    "is_goal_complete",
    "next_safe_task",
    "ready_tasks",
]
