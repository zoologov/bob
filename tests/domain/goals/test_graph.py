# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистых граф-функций Goal Engine (BOB-015 .1).

Покрывают готовность задач (топосорт по deps, только APPROVED/ACTIVE цели,
исключение внешне-агентных), выбор следующей безопасной задачи (по приоритету,
детерминированно), структурную завершённость цели, причину блокировки, выборку
внешне-агентных задач и устойчивость к циклам deps (не виснет).
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.domain.goals.entities import Goal, GoalOrigin, Task
from bob.domain.goals.graph import (
    GoalGraph,
    blocked_reason,
    external_agency_tasks,
    is_goal_complete,
    next_safe_task,
    ready_tasks,
)
from bob.domain.goals.state import GoalState, TaskState

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _goal(
    gid: str,
    *,
    state: GoalState = GoalState.ACTIVE,
    priority: int = 1,
) -> Goal:
    return Goal(
        id=gid,
        title=f"Цель {gid}",
        description="…",
        priority=priority,
        criteria="готово",
        state=state,
        created_at=_NOW,
        origin=GoalOrigin.OWNER,
    )


def _task(
    tid: str,
    goal_id: str,
    *,
    deps: tuple[str, ...] = (),
    state: TaskState = TaskState.NEW,
    external: bool = False,
) -> Task:
    return Task(
        id=tid,
        goal_id=goal_id,
        summary=f"Задача {tid}",
        deps=deps,
        state=state,
        needs_external_agency=external,
    )


def _graph(goals: tuple[Goal, ...], tasks: tuple[Task, ...]) -> GoalGraph:
    return GoalGraph(goals=goals, tasks=tasks)


# --- ready_tasks --------------------------------------------------------------


def test_ready_task_with_no_deps_on_active_goal() -> None:
    graph = _graph((_goal("g1"),), (_task("t1", "g1"),))

    ready = ready_tasks(graph)

    assert tuple(t.id for t in ready) == ("t1",)


def test_task_with_unfinished_dep_is_not_ready() -> None:
    graph = _graph(
        (_goal("g1"),),
        (_task("a", "g1"), _task("b", "g1", deps=("a",))),
    )

    ready = ready_tasks(graph)

    # Только "a" готова; "b" ждёт пока "a" не DONE.
    assert tuple(t.id for t in ready) == ("a",)


def test_task_becomes_ready_once_deps_done() -> None:
    graph = _graph(
        (_goal("g1"),),
        (
            _task("a", "g1", state=TaskState.DONE),
            _task("b", "g1", deps=("a",)),
        ),
    )

    ready = ready_tasks(graph)

    assert tuple(t.id for t in ready) == ("b",)


def test_tasks_of_unapproved_goal_are_never_ready() -> None:
    graph = _graph((_goal("g1", state=GoalState.PROPOSED),), (_task("t1", "g1"),))

    assert ready_tasks(graph) == ()


def test_approved_goal_tasks_are_ready() -> None:
    graph = _graph((_goal("g1", state=GoalState.APPROVED),), (_task("t1", "g1"),))

    assert tuple(t.id for t in ready_tasks(graph)) == ("t1",)


def test_external_agency_task_is_excluded_from_ready() -> None:
    graph = _graph(
        (_goal("g1"),),
        (_task("safe", "g1"), _task("ext", "g1", external=True)),
    )

    ready = ready_tasks(graph)

    assert tuple(t.id for t in ready) == ("safe",)


def test_only_new_and_ready_states_are_auto_ready() -> None:
    graph = _graph(
        (_goal("g1"),),
        (
            _task("a", "g1", state=TaskState.IN_PROGRESS),
            _task("b", "g1", state=TaskState.DONE),
            _task("c", "g1", state=TaskState.NEW),
        ),
    )

    assert tuple(t.id for t in ready_tasks(graph)) == ("c",)


def test_cyclic_deps_do_not_hang_and_yield_nothing() -> None:
    # Цикл a->b->a: ни одна задача не может стать готовой, функция не виснет.
    graph = _graph(
        (_goal("g1"),),
        (
            _task("a", "g1", deps=("b",)),
            _task("b", "g1", deps=("a",)),
        ),
    )

    assert ready_tasks(graph) == ()


# --- next_safe_task -----------------------------------------------------------


def test_next_safe_task_prefers_higher_priority_goal() -> None:
    graph = _graph(
        (_goal("lo", priority=1), _goal("hi", priority=5)),
        (_task("t_lo", "lo"), _task("t_hi", "hi")),
    )

    chosen = next_safe_task(graph)

    assert chosen is not None
    assert chosen.id == "t_hi"


def test_next_safe_task_is_deterministic() -> None:
    graph = _graph(
        (_goal("g1", priority=3),),
        (_task("t1", "g1"), _task("t2", "g1")),
    )

    first = next_safe_task(graph)
    second = next_safe_task(graph)

    assert first is not None
    assert first == second


def test_next_safe_task_none_when_nothing_ready() -> None:
    graph = _graph((_goal("g1", state=GoalState.PROPOSED),), (_task("t1", "g1"),))

    assert next_safe_task(graph) is None


def test_next_safe_task_never_returns_external_agency() -> None:
    graph = _graph((_goal("g1"),), (_task("ext", "g1", external=True),))

    assert next_safe_task(graph) is None


# --- is_goal_complete ---------------------------------------------------------


def test_goal_complete_when_all_non_skipped_tasks_done() -> None:
    goal = _goal("g1")
    tasks = (
        _task("a", "g1", state=TaskState.DONE),
        _task("b", "g1", state=TaskState.SKIPPED),
    )

    assert is_goal_complete(goal, tasks) is True


def test_goal_not_complete_with_outstanding_task() -> None:
    goal = _goal("g1")
    tasks = (
        _task("a", "g1", state=TaskState.DONE),
        _task("b", "g1", state=TaskState.IN_PROGRESS),
    )

    assert is_goal_complete(goal, tasks) is False


def test_goal_with_no_tasks_is_not_complete() -> None:
    # Без задач нет структурной завершённости (план ещё не построен).
    assert is_goal_complete(_goal("g1"), ()) is False


# --- blocked_reason -----------------------------------------------------------


def test_blocked_reason_none_when_ready() -> None:
    graph = _graph((_goal("g1"),), (_task("t1", "g1"),))

    assert blocked_reason(graph, graph.tasks[0]) is None


def test_blocked_reason_for_unfinished_dep() -> None:
    graph = _graph(
        (_goal("g1"),),
        (_task("a", "g1"), _task("b", "g1", deps=("a",))),
    )
    task_b = next(t for t in graph.tasks if t.id == "b")

    reason = blocked_reason(graph, task_b)

    assert reason is not None
    assert "a" in reason


def test_blocked_reason_for_inactive_goal() -> None:
    graph = _graph((_goal("g1", state=GoalState.PROPOSED),), (_task("t1", "g1"),))

    reason = blocked_reason(graph, graph.tasks[0])

    assert reason is not None


def test_blocked_reason_for_external_agency() -> None:
    graph = _graph((_goal("g1"),), (_task("ext", "g1", external=True),))

    reason = blocked_reason(graph, graph.tasks[0])

    assert reason is not None


# --- external_agency_tasks ----------------------------------------------------


def test_external_agency_tasks_lists_ready_external_of_approved_goals() -> None:
    graph = _graph(
        (_goal("g1"),),
        (
            _task("safe", "g1"),
            _task("ext", "g1", external=True),
        ),
    )

    ext = external_agency_tasks(graph)

    assert tuple(t.id for t in ext) == ("ext",)


def test_external_agency_tasks_excludes_unapproved_goal() -> None:
    graph = _graph(
        (_goal("g1", state=GoalState.PROPOSED),),
        (_task("ext", "g1", external=True),),
    )

    assert external_agency_tasks(graph) == ()


def test_external_agency_tasks_respects_deps() -> None:
    graph = _graph(
        (_goal("g1"),),
        (
            _task("a", "g1"),
            _task("ext", "g1", deps=("a",), external=True),
        ),
    )

    # ext зависит от незавершённой a -> ещё не готова к предложению.
    assert external_agency_tasks(graph) == ()
