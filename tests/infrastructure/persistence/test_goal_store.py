# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqliteGoalStore — per-persona персист графа целей (BOB-015 .1).

Round-trip: save_goal/save_task → load восстанавливает граф (цели, задачи,
состояния, deps, needs_external_agency); пустая персона даёт пустой граф;
атомарные апдейты состояний цели/задачи; per-persona изоляция; выживание
после рестарта.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.domain.goals.entities import Goal, GoalOrigin, Task
from bob.domain.goals.state import GoalState, TaskState
from bob.infrastructure.persistence.goal_store import SqliteGoalStore
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "bob"
_OTHER_PERSONA = "bender"
_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


def _goal(
    gid: str = "g1",
    *,
    state: GoalState = GoalState.PROPOSED,
    origin: GoalOrigin = GoalOrigin.OWNER,
    deadline: datetime | None = None,
) -> Goal:
    return Goal(
        id=gid,
        title="Выучить рекурсию",
        description="Разобраться в рекурсии",
        priority=3,
        criteria="Могу объяснить",
        state=state,
        created_at=_NOW,
        origin=origin,
        deadline=deadline,
    )


def _task(
    tid: str = "t1",
    *,
    goal_id: str = "g1",
    deps: tuple[str, ...] = (),
    state: TaskState = TaskState.NEW,
    external: bool = False,
) -> Task:
    return Task(
        id=tid,
        goal_id=goal_id,
        summary="Прочитать главу",
        deps=deps,
        state=state,
        needs_external_agency=external,
    )


async def test_load_empty_persona_yields_empty_graph(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)

    graph = await store.load(_PERSONA)

    assert graph.goals == ()
    assert graph.tasks == ()


async def test_save_goal_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    goal = _goal(deadline=_NOW)

    await store.save_goal(_PERSONA, goal)
    graph = await store.load(_PERSONA)

    assert graph.goals == (goal,)


async def test_save_task_round_trips_with_deps_and_external_flag(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal())
    task = _task("t2", deps=("t1", "t0"), external=True)

    await store.save_task(_PERSONA, task)
    graph = await store.load(_PERSONA)

    loaded = next(t for t in graph.tasks if t.id == "t2")
    assert loaded == task
    assert loaded.deps == ("t1", "t0")
    assert loaded.needs_external_agency is True


async def test_load_reconstructs_full_graph(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    goal = _goal(state=GoalState.ACTIVE)
    await store.save_goal(_PERSONA, goal)
    await store.save_task(_PERSONA, _task("a"))
    await store.save_task(_PERSONA, _task("b", deps=("a",)))

    graph = await store.load(_PERSONA)

    assert graph.goals == (goal,)
    assert tuple(sorted(t.id for t in graph.tasks)) == ("a", "b")


async def test_update_goal_state_is_atomic(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal(state=GoalState.PROPOSED))

    await store.update_goal_state(_PERSONA, "g1", GoalState.APPROVED)
    graph = await store.load(_PERSONA)

    assert graph.goals[0].state is GoalState.APPROVED


async def test_update_task_state_is_atomic(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal())
    await store.save_task(_PERSONA, _task("t1"))

    await store.update_task_state(_PERSONA, "t1", TaskState.DONE)
    graph = await store.load(_PERSONA)

    assert graph.tasks[0].state is TaskState.DONE


async def test_save_goal_upserts(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal(state=GoalState.PROPOSED))

    await store.save_goal(_PERSONA, _goal(state=GoalState.ACTIVE))
    graph = await store.load(_PERSONA)

    assert len(graph.goals) == 1
    assert graph.goals[0].state is GoalState.ACTIVE


async def test_save_task_upserts(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal())
    await store.save_task(_PERSONA, _task("t1", deps=("x",)))

    await store.save_task(_PERSONA, _task("t1", deps=(), state=TaskState.READY))
    graph = await store.load(_PERSONA)

    assert len(graph.tasks) == 1
    assert graph.tasks[0].state is TaskState.READY
    assert graph.tasks[0].deps == ()


async def test_personas_are_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteGoalStore(repo)
    await store.save_goal(_PERSONA, _goal("g1"))
    await store.save_goal(_OTHER_PERSONA, _goal("g2"))

    mine = await store.load(_PERSONA)
    other = await store.load(_OTHER_PERSONA)

    assert tuple(g.id for g in mine.goals) == ("g1",)
    assert tuple(g.id for g in other.goals) == ("g2",)


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    goal = _goal(state=GoalState.ACTIVE, origin=GoalOrigin.BOB_PROPOSED)
    task = _task("t1", deps=("t0",), external=True, state=TaskState.BLOCKED)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    store1 = SqliteGoalStore(first)
    await store1.save_goal(_PERSONA, goal)
    await store1.save_task(_PERSONA, task)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    graph = await SqliteGoalStore(second).load(_PERSONA)
    await second.close()

    assert graph.goals == (goal,)
    assert graph.tasks == (task,)
