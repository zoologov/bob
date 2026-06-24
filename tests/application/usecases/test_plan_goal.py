# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты LlmPlanner + PlanGoal use-case — декомпозиция + двойной апрув (BOB-015 .2).

Покрывает:
* ``LlmPlanner.decompose`` — строгий JSON из reasoning-модели (markdown-fenced,
  преамбула, мусор по краям), классификация ``needs_external_agency``, deps,
  задачи создаются в ``TaskState.NEW``; устойчивость к не-JSON (пустой список).
* ``PlanGoal`` — берёт APPROVED-цель → планнер → сохраняет задачи → формирует
  сообщение owner с планом; цель ОСТАЁТСЯ APPROVED (двойной гейт).
* Апрув плана (``PlanGoal.approve_plan``) → APPROVED→ACTIVE через ``can_transition``;
  при ``require_plan_approval=False`` декомпозиция сразу переводит в ACTIVE.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from bob.application.usecases.plan_goal import LlmPlanner, PlanGoal, PlanResult
from bob.domain.goals.entities import Goal, GoalOrigin, Task
from bob.domain.goals.graph import GoalGraph
from bob.domain.goals.state import GoalState, TaskState

_PERSONA = "bob"
_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _goal(gid: str = "g1", *, state: GoalState = GoalState.APPROVED) -> Goal:
    return Goal(
        id=gid,
        title="Выучить рекурсию",
        description="Разобраться в рекурсии и уметь объяснить",
        priority=3,
        criteria="Могу объяснить рекурсию",
        state=state,
        created_at=_NOW,
        origin=GoalOrigin.OWNER,
    )


# --- LlmPlanner ----------------------------------------------------------------


@dataclass
class _StubRouter:
    """LLMRouter double returning a canned raw completion string."""

    raw: str

    async def run(self, request: object) -> str:  # noqa: ARG002
        return self.raw


_FENCED = (
    "Думаю, разобью так.\n"
    "```json\n"
    "[\n"
    '  {"id": "a", "summary": "Прочитать главу", "deps": [],'
    ' "needs_external_agency": false},\n'
    '  {"id": "b", "summary": "Написать пример кода", "deps": ["a"],'
    ' "needs_external_agency": true}\n'
    "]\n"
    "```\n"
    "Готово."
)


@pytest.mark.asyncio
async def test_planner_parses_fenced_json_into_new_tasks() -> None:
    planner = LlmPlanner(router=_StubRouter(_FENCED))

    tasks = await planner.decompose(_goal())

    assert [t.summary for t in tasks] == ["Прочитать главу", "Написать пример кода"]
    assert all(t.state is TaskState.NEW for t in tasks)
    assert all(t.goal_id == "g1" for t in tasks)


@pytest.mark.asyncio
async def test_planner_classifies_external_agency_and_deps() -> None:
    planner = LlmPlanner(router=_StubRouter(_FENCED))

    tasks = await planner.decompose(_goal())

    first, second = tasks
    assert first.needs_external_agency is False
    assert first.deps == ()
    assert second.needs_external_agency is True
    # deps re-map onto the GENERATED task ids of this goal, not the model's local ids.
    assert second.deps == (first.id,)


@pytest.mark.asyncio
async def test_planner_task_ids_are_namespaced_and_unique() -> None:
    planner = LlmPlanner(router=_StubRouter(_FENCED))

    tasks = await planner.decompose(_goal("goalX"))

    ids = [t.id for t in tasks]
    assert len(set(ids)) == len(ids)
    assert all(tid.startswith("goalX") for tid in ids)


@pytest.mark.asyncio
async def test_planner_non_json_yields_no_tasks() -> None:
    planner = LlmPlanner(router=_StubRouter("извини, не смог разобрать"))

    tasks = await planner.decompose(_goal())

    assert tasks == ()


@pytest.mark.asyncio
async def test_planner_provider_error_yields_no_tasks() -> None:
    @dataclass
    class _Boom:
        async def run(self, request: object) -> str:  # noqa: ARG002
            raise RuntimeError("provider down")

    planner = LlmPlanner(router=_Boom())

    tasks = await planner.decompose(_goal())

    assert tasks == ()


# --- PlanGoal use-case (double approval) --------------------------------------


@dataclass
class _FakePlanner:
    tasks: tuple[Task, ...]

    async def decompose(self, goal: Goal) -> tuple[Task, ...]:  # noqa: ARG002
        return self.tasks


@dataclass
class _FakeGoalStore:
    """In-memory GoalStore double recording saved tasks + state moves."""

    goals: dict[str, Goal] = field(default_factory=dict)
    saved_tasks: list[Task] = field(default_factory=list)
    goal_states: dict[str, GoalState] = field(default_factory=dict)

    async def load(self, persona_id: str) -> GoalGraph:  # noqa: ARG002
        return GoalGraph(goals=tuple(self.goals.values()), tasks=())

    async def save_goal(self, persona_id: str, goal: Goal) -> None:  # noqa: ARG002
        self.goals[goal.id] = goal

    async def save_task(self, persona_id: str, task: Task) -> None:  # noqa: ARG002
        self.saved_tasks.append(task)

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState  # noqa: ARG002
    ) -> None:
        self.goal_states[goal_id] = state
        if goal_id in self.goals:
            self.goals[goal_id] = _with_state(self.goals[goal_id], state)

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:  # pragma: no cover - not exercised here
        pass


def _with_state(goal: Goal, state: GoalState) -> Goal:
    return replace(goal, state=state)


def _tasks() -> tuple[Task, ...]:
    return (
        Task(id="g1::t0", goal_id="g1", summary="Шаг 1", deps=(),
             state=TaskState.NEW, needs_external_agency=False),
        Task(id="g1::t1", goal_id="g1", summary="Запустить код", deps=("g1::t0",),
             state=TaskState.NEW, needs_external_agency=True),
    )


def _build_store(goal: Goal) -> _FakeGoalStore:
    store = _FakeGoalStore()
    store.goals[goal.id] = goal
    return store


@pytest.mark.asyncio
async def test_plan_goal_saves_tasks_and_keeps_goal_approved() -> None:
    goal = _goal()
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    result = await plan_goal.run("g1")

    assert isinstance(result, PlanResult)
    assert len(store.saved_tasks) == 2
    # Двойной гейт: цель остаётся APPROVED до апрува плана.
    assert "g1" not in store.goal_states or store.goal_states["g1"] is GoalState.APPROVED


@pytest.mark.asyncio
async def test_plan_goal_message_lists_tasks_deps_and_external_marks() -> None:
    goal = _goal()
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    result = await plan_goal.run("g1")

    assert "Шаг 1" in result.message
    assert "Запустить код" in result.message
    # внешне-агентная задача помечена в плане.
    assert "внешн" in result.message.lower()
    # зависимость отражена.
    assert "g1::t0" in result.message


@pytest.mark.asyncio
async def test_plan_goal_rejects_non_approved_goal() -> None:
    goal = _goal(state=GoalState.PROPOSED)
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    result = await plan_goal.run("g1")

    assert result.planned is False
    assert store.saved_tasks == []


@pytest.mark.asyncio
async def test_plan_goal_unknown_goal_is_safe() -> None:
    store = _FakeGoalStore()
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    result = await plan_goal.run("missing")

    assert result.planned is False


@pytest.mark.asyncio
async def test_plan_goal_auto_active_when_plan_approval_disabled() -> None:
    goal = _goal()
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()),
        store=store,
        persona_id=_PERSONA,
        require_plan_approval=False,
    )

    await plan_goal.run("g1")

    assert store.goal_states["g1"] is GoalState.ACTIVE


# --- plan approval (the second gate) ------------------------------------------


@pytest.mark.asyncio
async def test_approve_plan_moves_approved_to_active() -> None:
    goal = _goal()
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    moved = await plan_goal.approve_plan("g1")

    assert moved is True
    assert store.goal_states["g1"] is GoalState.ACTIVE


@pytest.mark.asyncio
async def test_approve_plan_rejects_illegal_transition() -> None:
    goal = _goal(state=GoalState.PROPOSED)
    store = _build_store(goal)
    plan_goal = PlanGoal(
        planner=_FakePlanner(_tasks()), store=store, persona_id=_PERSONA
    )

    moved = await plan_goal.approve_plan("g1")

    assert moved is False
    assert "g1" not in store.goal_states
