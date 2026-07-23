# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты GUPPI goal-команд (контроль owner) — BOB-015 .2.

Owner-only, в General-чате, по образцу /quiet:
* ``/goals`` — список целей + состояния (+задачи кратко);
* ``/goal approve <id>`` (PROPOSED→APPROVED);
* ``/goal plan <id>`` — запустить декомпозицию, показать план owner;
* ``/goal plan-approve <id>`` (APPROVED→ACTIVE) — второй гейт;
* ``/goal pause|resume|cancel <id>`` — через can_transition;
* ``/goals stop`` / ``/goals go`` — kill-switch (персист-флаг);
* не-owner / чужой чат / не-команда — игнор и тишина (authz-инвариант).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.telegram.guppi import GuppiHandler
from bob.proactivity.goals.entities import Goal, GoalOrigin, Task
from bob.proactivity.goals.graph import GoalGraph
from bob.proactivity.goals.state import GoalState, TaskState
from bob.proactivity.usecases.plan_goal import PlanGoal, PlanResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_OWNER_ID = 27468732
_STRANGER_ID = 555
_FOREIGN_CHAT_ID = -100999
_PERSONA = "bob"
_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    sends: list[_SendCall] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return _FakeMessage(message_id=0, text=text)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_chat_action(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover
        return _FakeMessage(message_id=0, text="")

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

@dataclass
class _FakeAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _FakeGoalStore:
    goals: dict[str, Goal] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)
    goal_states: dict[str, GoalState] = field(default_factory=dict)

    async def load(self, persona_id: str) -> GoalGraph:  # noqa: ARG002
        return GoalGraph(goals=tuple(self.goals.values()), tasks=tuple(self.tasks))

    async def save_goal(self, persona_id: str, goal: Goal) -> None:  # noqa: ARG002
        self.goals[goal.id] = goal

    async def save_task(self, persona_id: str, task: Task) -> None:  # noqa: ARG002
        self.tasks.append(task)

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState  # noqa: ARG002
    ) -> None:
        self.goal_states[goal_id] = state
        if goal_id in self.goals:
            self.goals[goal_id] = replace(self.goals[goal_id], state=state)

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:  # pragma: no cover
        pass


@dataclass
class _FakePursuitStore:
    stopped: bool = False

    async def set_pursuit_stopped(self, persona_id: str, *, stopped: bool) -> None:  # noqa: ARG002
        self.stopped = stopped

    async def is_pursuit_stopped(self, persona_id: str) -> bool:  # noqa: ARG002
        return self.stopped


@dataclass
class _FakePlanner:
    tasks: tuple[Task, ...] = ()

    async def decompose(self, goal: Goal) -> tuple[Task, ...]:  # noqa: ARG002
        return self.tasks


def _goal(gid: str = "g1", *, state: GoalState = GoalState.PROPOSED) -> Goal:
    return Goal(
        id=gid,
        title="Выучить рекурсию",
        description="Разобраться",
        priority=3,
        criteria="Объяснить",
        state=state,
        created_at=_NOW,
        origin=GoalOrigin.OWNER,
    )


def _task(tid: str = "g1::t0", *, external: bool = False) -> Task:
    return Task(
        id=tid,
        goal_id="g1",
        summary="Прочитать главу",
        deps=(),
        state=TaskState.NEW,
        needs_external_agency=external,
    )


def _build(
    *,
    goals: dict[str, Goal] | None = None,
    planner_tasks: tuple[Task, ...] = (),
) -> tuple[GuppiHandler, _FakeBot, _FakeGoalStore, _FakePursuitStore]:
    bot = _FakeBot()
    goal_store = _FakeGoalStore(goals=goals or {})
    pursuit = _FakePursuitStore()
    plan_goal = PlanGoal(
        planner=_FakePlanner(planner_tasks), store=goal_store, persona_id=_PERSONA
    )
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        goal_store=goal_store,
        plan_goal=plan_goal,
        pursuit_store=pursuit,
        persona_id=_PERSONA,
    )
    return handler, bot, goal_store, pursuit


async def _send(handler: GuppiHandler, text: str, *, user_id: int = _OWNER_ID,
                chat_id: int = _CHAT_ID) -> bool:
    return await handler.handle_general_command(text=text, user_id=user_id, chat_id=chat_id)


# --- /goals list --------------------------------------------------------------


@pytest.mark.asyncio
async def test_goals_lists_goals_with_states() -> None:
    handler, bot, _, _ = _build(goals={"g1": _goal(state=GoalState.ACTIVE)})

    handled = await _send(handler, "/goals")

    assert handled is True
    assert "Выучить рекурсию" in bot.sends[0].text
    assert "active" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goals_empty_is_friendly() -> None:
    handler, bot, _, _ = _build()

    handled = await _send(handler, "/goals")

    assert handled is True
    assert len(bot.sends) == 1


# --- /goal approve ------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_approve_moves_proposed_to_approved() -> None:
    handler, _, store, _ = _build(goals={"g1": _goal(state=GoalState.PROPOSED)})

    handled = await _send(handler, "/goal approve g1")

    assert handled is True
    assert store.goal_states["g1"] is GoalState.APPROVED


@pytest.mark.asyncio
async def test_goal_approve_rejects_illegal_transition() -> None:
    handler, bot, store, _ = _build(goals={"g1": _goal(state=GoalState.ACTIVE)})

    handled = await _send(handler, "/goal approve g1")

    assert handled is True
    assert "g1" not in store.goal_states
    assert len(bot.sends) == 1  # a rejection message, no state change


# --- /goal plan + plan-approve (double gate) ----------------------------------


@pytest.mark.asyncio
async def test_goal_plan_decomposes_and_shows_plan_but_keeps_approved() -> None:
    handler, bot, store, _ = _build(
        goals={"g1": _goal(state=GoalState.APPROVED)},
        planner_tasks=(_task(), _task("g1::t1", external=True)),
    )

    handled = await _send(handler, "/goal plan g1")

    assert handled is True
    assert len(store.tasks) == 2
    # цель остаётся APPROVED — план ещё не одобрен (двойной гейт).
    assert "g1" not in store.goal_states or store.goal_states["g1"] is GoalState.APPROVED
    assert "План" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_plan_approve_moves_approved_to_active() -> None:
    handler, _, store, _ = _build(goals={"g1": _goal(state=GoalState.APPROVED)})

    handled = await _send(handler, "/goal plan-approve g1")

    assert handled is True
    assert store.goal_states["g1"] is GoalState.ACTIVE


# --- /goal pause | resume | cancel --------------------------------------------


@pytest.mark.asyncio
async def test_goal_pause_resume_cancel() -> None:
    handler, _, store, _ = _build(goals={"g1": _goal(state=GoalState.ACTIVE)})

    assert await _send(handler, "/goal pause g1") is True
    assert store.goal_states["g1"].value == GoalState.PAUSED.value

    assert await _send(handler, "/goal resume g1") is True
    assert store.goal_states["g1"].value == GoalState.ACTIVE.value

    assert await _send(handler, "/goal cancel g1") is True
    assert store.goal_states["g1"].value == GoalState.CANCELLED.value


# --- /goals stop | go (kill-switch) -------------------------------------------


@pytest.mark.asyncio
async def test_goals_stop_sets_kill_switch() -> None:
    handler, _, _, pursuit = _build()

    handled = await _send(handler, "/goals stop")

    assert handled is True
    assert pursuit.stopped is True


@pytest.mark.asyncio
async def test_goals_go_clears_kill_switch() -> None:
    handler, _, _, pursuit = _build()
    pursuit.stopped = True

    handled = await _send(handler, "/goals go")

    assert handled is True
    assert pursuit.stopped is False


# --- authz: owner-only --------------------------------------------------------


@pytest.mark.asyncio
async def test_stranger_cannot_manage_goals() -> None:
    handler, bot, store, _pursuit = _build(goals={"g1": _goal(state=GoalState.PROPOSED)})

    handled = await _send(handler, "/goal approve g1", user_id=_STRANGER_ID)

    assert handled is False
    assert store.goal_states == {}
    assert bot.sends == []


@pytest.mark.asyncio
async def test_foreign_chat_cannot_manage_goals() -> None:
    handler, bot, _, pursuit = _build()

    handled = await _send(handler, "/goals stop", chat_id=_FOREIGN_CHAT_ID)

    assert handled is False
    assert pursuit.stopped is False
    assert bot.sends == []


@pytest.mark.asyncio
async def test_unknown_goal_command_not_consumed() -> None:
    handler, _, _, _ = _build()

    handled = await _send(handler, "/goal frobnicate g1")

    assert handled is False


def test_plan_result_shape() -> None:
    result = PlanResult(planned=True, tasks=(), message="x")
    assert result.planned is True


# --- usage / not-found / illegal-transition feedback --------------------------


@pytest.mark.asyncio
async def test_goal_action_without_id_shows_usage() -> None:
    handler, bot, store, _ = _build(goals={"g1": _goal(state=GoalState.APPROVED)})

    # `/goal approve` with no id is consumed (True) but only echoes usage, no move.
    handled = await _send(handler, "/goal approve")

    assert handled is True
    assert store.goal_states == {}
    assert "Использование" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_state_move_on_missing_goal_reports_not_found() -> None:
    handler, bot, store, _ = _build(goals={})

    handled = await _send(handler, "/goal pause ghost")

    assert handled is True
    assert store.goal_states == {}
    assert "не найдена" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_plan_approve_missing_goal_reports_not_found() -> None:
    handler, bot, _, _ = _build(goals={})

    handled = await _send(handler, "/goal plan-approve ghost")

    assert handled is True
    assert "не найдена" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_plan_approve_illegal_transition_reports_reject() -> None:
    # The goal exists but is PROPOSED → plan-approve can't move it; the owner gets a
    # rejection naming the current state (not a silent no-op).
    handler, bot, store, _ = _build(goals={"g1": _goal(state=GoalState.PROPOSED)})

    handled = await _send(handler, "/goal plan-approve g1")

    assert handled is True
    assert "g1" not in store.goal_states
    assert "недопустим" in bot.sends[0].text
    assert "proposed" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_state_move_illegal_transition_names_current_state() -> None:
    handler, bot, store, _ = _build(goals={"g1": _goal(state=GoalState.DONE)})

    handled = await _send(handler, "/goal pause g1")

    assert handled is True
    assert "g1" not in store.goal_states
    assert "недопустим" in bot.sends[0].text


# --- kill-switch list reflects state ------------------------------------------


@pytest.mark.asyncio
async def test_goals_list_shows_task_counts() -> None:
    handler, bot, store, _ = _build(goals={"g1": _goal(state=GoalState.ACTIVE)})
    store.tasks.append(_task("g1::t0"))

    handled = await _send(handler, "/goals")

    assert handled is True
    assert "задач: 1" in bot.sends[0].text


# --- unwired sub-stores degrade gracefully (no crash, owner is told) ----------


def _build_without(
    *,
    drop_goal_store: bool = False,
    drop_plan: bool = False,
    drop_pursuit: bool = False,
    goals: dict[str, Goal] | None = None,
) -> tuple[GuppiHandler, _FakeBot, _FakeGoalStore]:
    bot = _FakeBot()
    goal_store = _FakeGoalStore(goals=goals or {})
    plan_goal = (
        None
        if drop_plan
        else PlanGoal(planner=_FakePlanner(()), store=goal_store, persona_id=_PERSONA)
    )
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        goal_store=None if drop_goal_store else goal_store,
        plan_goal=plan_goal,
        pursuit_store=None if drop_pursuit else _FakePursuitStore(),
        persona_id=_PERSONA,
    )
    return handler, bot, goal_store


@pytest.mark.asyncio
async def test_goals_command_not_consumed_when_goal_store_unwired() -> None:
    # With no goal store wired, the goal commands are simply not GUPPI's — they fall
    # through (False), never crash.
    handler, bot, _ = _build_without(drop_goal_store=True)

    handled = await _send(handler, "/goals")

    assert handled is False
    assert bot.sends == []


@pytest.mark.asyncio
async def test_kill_switch_reports_unavailable_when_pursuit_store_unwired() -> None:
    handler, bot, _ = _build_without(drop_pursuit=True)

    handled = await _send(handler, "/goals stop")

    assert handled is True
    assert "не подключено" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_plan_reports_unavailable_when_plan_use_case_unwired() -> None:
    handler, bot, _ = _build_without(
        drop_plan=True, goals={"g1": _goal(state=GoalState.APPROVED)}
    )

    handled = await _send(handler, "/goal plan g1")

    assert handled is True
    assert "не подключено" in bot.sends[0].text


@pytest.mark.asyncio
async def test_goal_plan_approve_reports_unavailable_when_plan_use_case_unwired() -> None:
    handler, bot, _ = _build_without(
        drop_plan=True, goals={"g1": _goal(state=GoalState.APPROVED)}
    )

    handled = await _send(handler, "/goal plan-approve g1")

    assert handled is True
    assert "не подключено" in bot.sends[0].text


# --- authz: a non-command from the owner is not consumed ----------------------


@pytest.mark.asyncio
async def test_owner_non_goal_command_falls_through() -> None:
    handler, bot, _, _ = _build()

    handled = await _send(handler, "просто болтаю")

    assert handled is False
    assert bot.sends == []
