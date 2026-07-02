# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=goals

"""Доменные дата-классы Goal Engine — immutable value-objects (BOB-015 .1).

``Goal`` (цель: что и зачем, критерий завершения, состояние, происхождение) и
``Task`` (единица работы цели: краткое описание, зависимости-предшественники,
состояние, и флаг ``needs_external_agency`` — нужна ли стадия-C: код/внешние
инструменты/ФС/внешние API). Оба — ``frozen, slots``: без I/O, без часов,
детерминированно тестируемы и переиспользуемы графом, стором и use-case'ами.

``GoalOrigin`` различает цель, поставленную владельцем (``OWNER``), и цель,
предложенную самим Бобом (``BOB_PROPOSED``) — тик (.3) никогда не трогает
неутверждённое предложение.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — runtime-needed for the frozen field type
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.goals.state import GoalState, TaskState

__all__ = [
    "Goal",
    "GoalOrigin",
    "Task",
]


class GoalOrigin(StrEnum):
    """Происхождение цели: поставлена владельцем или предложена Бобом.

    ``OWNER`` — цель от владельца; ``BOB_PROPOSED`` — Боб сам предложил её из
    паттернов диалога/памяти (``state=PROPOSED``, ждёт owner-апрува). Строковый
    ``Enum`` — значение кладётся прямо в SQLite TEXT-колонку.
    """

    OWNER = "owner"
    BOB_PROPOSED = "bob_proposed"


@dataclass(frozen=True, slots=True)
class Goal:
    """Цель Боба — что и зачем, с критерием завершения и состоянием.

    ``priority`` — целочисленный приоритет (больше = важнее), задаёт порядок
    выбора задач тиком. ``criteria`` — текстовый критерий завершения (структурную
    завершённость даёт граф; текстовый критерий проверяет use-case/owner).
    ``deadline`` опционален. ``origin`` различает owner-цель и предложение Боба.
    """

    id: str
    title: str
    description: str
    priority: int
    criteria: str
    state: GoalState
    created_at: datetime
    origin: GoalOrigin
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class Task:
    """Единица работы цели — что сделать, от чего зависит, и безопасна ли она.

    ``deps`` — id задач-предшественников (та же цель): задача готова к продвижению
    только когда все они ``DONE`` (топосорт строится из этого). ``state`` —
    :class:`TaskState`. ``needs_external_agency`` — требует ли стадии-C
    (код/внешние инструменты/ФС/внешние API): такие задачи НИКОГДА не исполняются
    автономно (только предлагаются owner в .3) и исключены из авто-готовых.
    """

    id: str
    goal_id: str
    summary: str
    deps: tuple[str, ...]
    state: TaskState
    needs_external_agency: bool
