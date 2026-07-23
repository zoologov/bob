# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Машины состояний Goal Engine — чистые, детерминированные (BOB-015 .1).

``GoalState`` и ``TaskState`` — строковые ``Enum`` (значения совпадают с тем, что
кладётся в SQLite TEXT-колонки, так round-trip тривиален). Разрешённые переходы
заданы таблицами; :func:`can_transition` / :func:`can_transition_task` — чистые
предикаты «можно ли перейти из ``frm`` в ``to``».

КЛЮЧЕВОЕ (authz-before-autonomy): переход ``PROPOSED → APPROVED`` — валиден на
уровне домена, но его ИНИЦИИРУЕТ только owner-апрув на уровне use-case (.2);
самонаправленный тик (.3) работает ТОЛЬКО с целями в ``APPROVED`` / ``ACTIVE`` и
никогда не трогает ``PROPOSED``. Переход в ``ACTIVE`` минует ``APPROVED`` нельзя —
двойной гейт (цель, затем план) консервативен на старте автономии.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "GoalState",
    "TaskState",
    "can_transition",
    "can_transition_task",
]


class GoalState(StrEnum):
    """Состояние цели — машина жизненного цикла под governance.

    ``PROPOSED`` (предложена, ждёт owner-апрува) → ``APPROVED`` (одобрена, ждёт
    плана) → ``ACTIVE`` (план одобрен, тик может продвигать) ↔ ``BLOCKED`` (упёрлась)
    → терминальные ``DONE`` / ``CANCELLED``; ``PAUSED`` — временная остановка
    owner'ом, обратимая в ``ACTIVE``.
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskState(StrEnum):
    """Состояние задачи — единицы работы цели.

    ``NEW`` (создана планнером) → ``READY`` (deps выполнены) → ``IN_PROGRESS`` →
    терминальный ``DONE``; ``BLOCKED`` — упёрлась (обратима в ``READY``);
    ``SKIPPED`` — пропущена (терминальный, не мешает завершению цели).
    """

    NEW = "new"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


# Разрешённые переходы цели. PROPOSED->APPROVED только owner-апрувом (use-case .2);
# ACTIVE минуя APPROVED нельзя (двойной гейт). DONE/CANCELLED — терминальные.
_GOAL_TRANSITIONS: dict[GoalState, frozenset[GoalState]] = {
    GoalState.PROPOSED: frozenset({GoalState.APPROVED, GoalState.CANCELLED}),
    GoalState.APPROVED: frozenset(
        {GoalState.ACTIVE, GoalState.PAUSED, GoalState.CANCELLED}
    ),
    GoalState.ACTIVE: frozenset(
        {
            GoalState.BLOCKED,
            GoalState.DONE,
            GoalState.PAUSED,
            GoalState.CANCELLED,
        }
    ),
    GoalState.BLOCKED: frozenset(
        {GoalState.ACTIVE, GoalState.CANCELLED, GoalState.PAUSED}
    ),
    GoalState.PAUSED: frozenset({GoalState.ACTIVE, GoalState.CANCELLED}),
    GoalState.DONE: frozenset(),
    GoalState.CANCELLED: frozenset(),
}

# Разрешённые переходы задачи. NEW->DONE нельзя (через READY/IN_PROGRESS).
# DONE/SKIPPED — терминальные.
_TASK_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.NEW: frozenset(
        {TaskState.READY, TaskState.BLOCKED, TaskState.SKIPPED}
    ),
    TaskState.READY: frozenset(
        {TaskState.IN_PROGRESS, TaskState.BLOCKED, TaskState.SKIPPED}
    ),
    TaskState.IN_PROGRESS: frozenset(
        {TaskState.DONE, TaskState.BLOCKED, TaskState.SKIPPED}
    ),
    TaskState.BLOCKED: frozenset(
        {TaskState.READY, TaskState.SKIPPED, TaskState.IN_PROGRESS}
    ),
    TaskState.DONE: frozenset(),
    TaskState.SKIPPED: frozenset(),
}


def can_transition(frm: GoalState, to: GoalState) -> bool:
    """Можно ли перевести цель из ``frm`` в ``to`` (чистый предикат).

    Самопереход (``frm == to``) переходом НЕ считается. Терминальные состояния
    (``DONE`` / ``CANCELLED``) не имеют исходящих переходов.
    """
    return to in _GOAL_TRANSITIONS[frm]


def can_transition_task(frm: TaskState, to: TaskState) -> bool:
    """Можно ли перевести задачу из ``frm`` в ``to`` (чистый предикат)."""
    return to in _TASK_TRANSITIONS[frm]
