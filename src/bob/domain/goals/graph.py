# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Граф целей Боба + чистые граф-функции (BOB-015 .1).

:class:`GoalGraph` — immutable-снимок набора целей и задач, который стор отдаёт
use-case'ам. Поверх него — чистые, детерминированные функции готовности и выбора:

* :func:`ready_tasks` — задачи, готовые к АВТО-продвижению: цель в
  ``APPROVED`` / ``ACTIVE``, все ``deps`` в ``DONE``, состояние ``NEW`` / ``READY``,
  ИСКЛЮЧАЯ ``needs_external_agency`` (внешне-агентные домен помечает отдельно).
* :func:`next_safe_task` — следующая безопасная задача к продвижению, по приоритету
  цели, детерминированно (стабильный tie-break по id).
* :func:`is_goal_complete` — структурная завершённость: все НЕ-skipped задачи цели
  в ``DONE`` (текстовый критерий проверяет use-case/owner).
* :func:`blocked_reason` — почему задача не готова (незавершённые deps / цель не
  активна / внешне-агентная), либо ``None`` если готова.
* :func:`external_agency_tasks` — внешне-агентные задачи готовых целей (для
  предложения owner в .3).

Всё без I/O и без часов; устойчиво к циклам ``deps`` (не виснет — обход без
рекурсии по факту наличия незавершённого предшественника, а не по топосорту).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.domain.goals.state import GoalState, TaskState

if TYPE_CHECKING:
    from bob.domain.goals.entities import Goal, Task

__all__ = [
    "GoalGraph",
    "blocked_reason",
    "external_agency_tasks",
    "is_goal_complete",
    "next_safe_task",
    "ready_tasks",
]

# Цели, по которым тик вправе продвигать задачи (authz-before-autonomy): только
# одобренные владельцем. PROPOSED / PAUSED / BLOCKED / терминальные — недостижимы.
_PURSUABLE_GOAL_STATES: frozenset[GoalState] = frozenset(
    {GoalState.APPROVED, GoalState.ACTIVE}
)

# Состояния задачи, из которых она может стать авто-готовой к продвижению.
_ADVANCEABLE_TASK_STATES: frozenset[TaskState] = frozenset(
    {TaskState.NEW, TaskState.READY}
)


@dataclass(frozen=True, slots=True)
class GoalGraph:
    """Immutable-снимок целей и задач одной персоны (то, что round-trip'ит стор)."""

    goals: tuple[Goal, ...]
    tasks: tuple[Task, ...]

    def goal_by_id(self, goal_id: str) -> Goal | None:
        """Вернуть цель по id, либо ``None`` если её нет в снимке."""
        for goal in self.goals:
            if goal.id == goal_id:
                return goal
        return None

    def tasks_of(self, goal_id: str) -> tuple[Task, ...]:
        """Вернуть задачи указанной цели (в порядке снимка)."""
        return tuple(task for task in self.tasks if task.goal_id == goal_id)


def _done_task_ids(graph: GoalGraph) -> frozenset[str]:
    """Множество id задач в состоянии ``DONE`` (для проверки готовности deps)."""
    return frozenset(task.id for task in graph.tasks if task.state is TaskState.DONE)


def _deps_satisfied(task: Task, done_ids: frozenset[str]) -> bool:
    """Все ли предшественники задачи завершены (чистая проверка, без рекурсии).

    Циклы ``deps`` безопасны: незавершённый предшественник (в т.ч. участник цикла)
    просто делает задачу неготовой — обхода графа нет, зависнуть негде.
    """
    return all(dep_id in done_ids for dep_id in task.deps)


def _goal_is_pursuable(graph: GoalGraph, task: Task) -> bool:
    """Принадлежит ли задача цели, которую тик вправе продвигать (APPROVED/ACTIVE)."""
    goal = graph.goal_by_id(task.goal_id)
    return goal is not None and goal.state in _PURSUABLE_GOAL_STATES


def ready_tasks(graph: GoalGraph) -> tuple[Task, ...]:
    """Задачи, готовые к АВТО-продвижению (внешне-агентные исключены).

    Цель в ``APPROVED`` / ``ACTIVE``; состояние задачи ``NEW`` / ``READY``; все
    ``deps`` в ``DONE``; ``needs_external_agency`` ложно. Порядок сохраняет порядок
    снимка (детерминирован).
    """
    done_ids = _done_task_ids(graph)
    return tuple(
        task
        for task in graph.tasks
        if task.state in _ADVANCEABLE_TASK_STATES
        and not task.needs_external_agency
        and _goal_is_pursuable(graph, task)
        and _deps_satisfied(task, done_ids)
    )


def _goal_priority(graph: GoalGraph, task: Task) -> int:
    """Приоритет цели задачи (отсутствующая цель → минимальный приоритет)."""
    goal = graph.goal_by_id(task.goal_id)
    return goal.priority if goal is not None else 0


def next_safe_task(graph: GoalGraph) -> Task | None:
    """Следующая безопасная задача к продвижению, либо ``None``.

    Выбор детерминирован: максимальный приоритет цели, при равенстве — стабильный
    tie-break по id задачи. Внешне-агентные сюда никогда не попадают (их уже
    исключил :func:`ready_tasks`).
    """
    ready = ready_tasks(graph)
    if not ready:
        return None
    return max(ready, key=lambda task: (_goal_priority(graph, task), task.id))


def is_goal_complete(goal: Goal, tasks: tuple[Task, ...]) -> bool:
    """Структурная завершённость цели: все НЕ-skipped задачи в ``DONE``.

    Цель без задач завершённой НЕ считается (план ещё не построен). Текстовый
    критерий (:attr:`Goal.criteria`) домен не проверяет — это делает use-case/owner;
    домен даёт только структурный предикат.
    """
    own = tuple(task for task in tasks if task.goal_id == goal.id)
    relevant = tuple(task for task in own if task.state is not TaskState.SKIPPED)
    if not relevant:
        return False
    return all(task.state is TaskState.DONE for task in relevant)


def blocked_reason(graph: GoalGraph, task: Task) -> str | None:
    """Почему задача не готова к авто-продвижению, либо ``None`` если готова.

    Порядок проверок: внешне-агентная → цель не активна → незавершённые deps →
    неподходящее состояние. Возвращает короткую человекочитаемую причину (рус).
    """
    if task.needs_external_agency:
        return "требует внешней агентности (стадия C) — только предложение owner"

    goal = graph.goal_by_id(task.goal_id)
    if goal is None:
        return "цель задачи отсутствует в графе"
    if goal.state not in _PURSUABLE_GOAL_STATES:
        return f"цель не активна (состояние {goal.state.value})"

    done_ids = _done_task_ids(graph)
    pending = tuple(dep for dep in task.deps if dep not in done_ids)
    if pending:
        return f"ждёт незавершённых задач: {', '.join(pending)}"

    if task.state not in _ADVANCEABLE_TASK_STATES:
        return f"состояние задачи не продвигаемо ({task.state.value})"

    return None


def external_agency_tasks(graph: GoalGraph) -> tuple[Task, ...]:
    """Внешне-агентные задачи готовых целей (для предложения owner в .3).

    Те же ворота готовности, что у :func:`ready_tasks` (цель ``APPROVED``/``ACTIVE``,
    состояние ``NEW``/``READY``, deps выполнены), НО ``needs_external_agency`` истинно
    — это кандидаты на стадию-C гейт, а не на авто-исполнение.
    """
    done_ids = _done_task_ids(graph)
    return tuple(
        task
        for task in graph.tasks
        if task.needs_external_agency
        and task.state in _ADVANCEABLE_TASK_STATES
        and _goal_is_pursuable(graph, task)
        and _deps_satisfied(task, done_ids)
    )
