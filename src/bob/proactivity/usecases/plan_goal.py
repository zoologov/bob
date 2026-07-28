# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""LlmPlanner + PlanGoal — декомпозиция цели и ДВОЙНОЙ апрув (BOB-015 .2).

Две части, обе чисто-оркестрационные (домен остаётся I/O-free):

* :class:`LlmPlanner` реализует порт :class:`bob.proactivity.ports.Planner`: просит
  reasoning-модель (Tier 1, ``TaskType.PLAN_GOAL``) разбить APPROVED-цель на
  атомарные задачи и парсит СТРОГИЙ JSON так же устойчиво, как извлечение фактов
  (markdown-fence / преамбула / мусор по краям терпятся). Каждый элемент несёт
  ``deps`` (по локальным id модели) и обязательный ``needs_external_agency`` —
  флаг стадии-C (код/внешние инструменты/ФС/внешние API). Локальные id модели
  ремапятся на сгенерированные ``<goal_id>::<n>`` (детерминированно), задачи —
  в ``TaskState.NEW``. Не-JSON / ошибка провайдера → пустой план (best-effort).

* :class:`PlanGoal` — use-case двойного гейта. :meth:`run` берёт цель в
  ``APPROVED`` (одобрена owner'ом, плана ещё нет) → :class:`Planner` → сохраняет
  задачи → формирует сообщение owner с планом (список, зависимости, пометки
  внешне-агентных). Цель ОСТАЁТСЯ ``APPROVED`` — до явного апрува плана
  (:meth:`approve_plan`, ``APPROVED → ACTIVE`` через :func:`can_transition`).
  Конфиг ``goals.require_plan_approval`` (default ``True``); при ``False``
  декомпозиция сразу переводит цель в ``ACTIVE`` (одинарный гейт).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.proactivity.goals.entities import Task
from bob.proactivity.goals.state import GoalState, TaskState, can_transition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.router.llm_router import LLMRouter
    from bob.proactivity.goals.entities import Goal
    from bob.proactivity.goals.graph import GoalGraph
    from bob.proactivity.ports import Planner

logger = logging.getLogger(__name__)

__all__ = [
    "LlmPlanner",
    "PlanGoal",
    "PlanResult",
]


class _GoalRouter(Protocol):
    """The router surface the planner needs: run a request, return raw text."""

    async def run(self, request: LLMRequest) -> str: ...


class _GoalStoreLike(Protocol):
    """The GoalStore surface PlanGoal needs (load + save_task + state move)."""

    async def load(self, persona_id: str) -> GoalGraph: ...
    async def save_task(self, persona_id: str, task: Task) -> None: ...
    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None: ...


_SYSTEM_PROMPT = (
    "Ты планировщик. Разбей цель на АТОМАРНЫЕ задачи. Ответь ТОЛЬКО JSON-массивом "
    "объектов, каждый вида "
    '{"id": "<короткий локальный id>", "summary": "<что сделать>", '
    '"deps": ["<id предшественников из этого же массива>"], '
    '"needs_external_agency": <true|false>}. '
    "Ставь needs_external_agency=true ТОЛЬКО если задача требует написать/запустить "
    "код, обратиться к внешним инструментам, файловой системе или внешним API "
    "(иначе false — это обычная задача: подумать, вспомнить, найти в памяти, "
    "сделать заметку, подготовить). Если задач нет — ответь []."
)


class LlmPlanner:
    """Декомпозиция цели → задачи через reasoning-модель (порт :class:`Planner`)."""

    def __init__(self, *, router: LLMRouter | _GoalRouter) -> None:
        self._router = router

    async def decompose(self, goal: Goal) -> Sequence[Task]:
        """Вернуть задачи, на которые раскладывается ``goal`` (в ``TaskState.NEW``).

        Best-effort: ошибка провайдера или непарсимый ответ дают ПУСТОЙ план,
        а не исключение — план потом покажется owner и может быть перезапущен.
        """
        try:
            raw = await self._ask(goal)
        except Exception:
            logger.exception("Planner decomposition failed; empty plan (best-effort)")
            return ()
        return _to_tasks(goal.id, _parse_plan(raw))

    async def _ask(self, goal: Goal) -> str:
        request = LLMRequest(
            task_type=TaskType.PLAN_GOAL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _render_goal(goal)},
            ],
        )
        return await self._router.run(request)


class PlanResult:
    """Итог :meth:`PlanGoal.run` — был ли построен план и сообщение owner."""

    __slots__ = ("message", "planned", "tasks")

    def __init__(self, *, planned: bool, tasks: tuple[Task, ...], message: str) -> None:
        self.planned = planned
        self.tasks = tasks
        self.message = message


class PlanGoal:
    """Декомпозиция APPROVED-цели + ДВОЙНОЙ апрув (план → ACTIVE по апруву)."""

    def __init__(
        self,
        *,
        planner: Planner | _PlannerLike,
        store: _GoalStoreLike,
        persona_id: str,
        require_plan_approval: bool = True,
    ) -> None:
        self._planner = planner
        self._store = store
        self._persona_id = persona_id
        self._require_plan_approval = require_plan_approval

    async def run(self, goal_id: str) -> PlanResult:
        """Декомпозировать цель ``goal_id`` (должна быть ``APPROVED``).

        Сохраняет задачи и возвращает план для owner; цель остаётся ``APPROVED``
        до апрува плана. При ``require_plan_approval=False`` сразу → ``ACTIVE``.
        Не-APPROVED или отсутствующая цель → ничего не делает (``planned=False``).
        """
        goal = await self._load_goal(goal_id)
        if goal is None or goal.state is not GoalState.APPROVED:
            return PlanResult(planned=False, tasks=(), message=_NO_PLAN_MESSAGE)
        tasks = tuple(await self._planner.decompose(goal))
        for task in tasks:
            await self._store.save_task(self._persona_id, task)
        if not self._require_plan_approval:
            await self._activate(goal_id)
        return PlanResult(planned=True, tasks=tasks, message=_render_plan(goal, tasks))

    async def approve_plan(self, goal_id: str) -> bool:
        """Апрув плана owner'ом: ``APPROVED → ACTIVE`` (второй гейт).

        Возвращает ``True`` при выполненном переходе. Нелегальный переход (цель не
        в ``APPROVED``) или отсутствие цели → ``False``, состояние не трогается.
        """
        goal = await self._load_goal(goal_id)
        if goal is None or not can_transition(goal.state, GoalState.ACTIVE):
            return False
        await self._activate(goal_id)
        return True

    async def _activate(self, goal_id: str) -> None:
        await self._store.update_goal_state(self._persona_id, goal_id, GoalState.ACTIVE)

    async def _load_goal(self, goal_id: str) -> Goal | None:
        graph = await self._store.load(self._persona_id)
        return graph.goal_by_id(goal_id)


class _PlannerLike(Protocol):
    """Structural Planner surface (so a fake/impl satisfies PlanGoal in tests)."""

    async def decompose(self, goal: Goal) -> Sequence[Task]: ...


_NO_PLAN_MESSAGE = "Цель не в состоянии «одобрена» или не найдена — план не построен."


def _render_goal(goal: Goal) -> str:
    """Render the goal the planner should decompose (title + description + criteria)."""
    return (
        f"Цель: {goal.title}\n"
        f"Описание: {goal.description}\n"
        f"Критерий завершения: {goal.criteria}"
    )


def _render_plan(goal: Goal, tasks: tuple[Task, ...]) -> str:
    """Render the owner-facing plan message (tasks, deps, external-agency marks)."""
    if not tasks:
        return f"Цель «{goal.title}»: план пуст — не удалось разложить на задачи."
    lines = [f"План для цели «{goal.title}»:"]
    for index, task in enumerate(tasks, start=1):
        line = f"{index}. {task.summary}"
        if task.deps:
            line += f" (зависит от: {', '.join(task.deps)})"
        if task.needs_external_agency:
            line += " [внешняя агентность — стадия C, отдельный гейт]"
        lines.append(line)
    lines.append("Одобрить план? /goal plan-approve " + goal.id)
    return "\n".join(lines)


def _to_tasks(goal_id: str, items: list[tuple[str, str, list[str], bool]]) -> tuple[Task, ...]:
    """Map parsed plan items to domain Tasks (ids namespaced, deps re-mapped).

    The model's local ids are remapped onto generated ``<goal_id>::<n>`` task ids
    so plans never collide across goals; ``deps`` referencing a local id resolve to
    the generated id (an unknown dep is dropped). All tasks start in ``NEW``.
    """
    local_to_id = {local: f"{goal_id}::t{index}" for index, (local, _, _, _) in enumerate(items)}
    tasks: list[Task] = []
    for local, summary, deps, external in items:
        mapped_deps = tuple(local_to_id[d] for d in deps if d in local_to_id)
        tasks.append(
            Task(
                id=local_to_id[local],
                goal_id=goal_id,
                summary=summary,
                deps=mapped_deps,
                state=TaskState.NEW,
                needs_external_agency=external,
            )
        )
    return tuple(tasks)


# --- JSON parsing (tolerant, mirrors fact extraction) -------------------------

# Markdown code fence, optionally tagged (``` or ```json), capturing its body.
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _strip_code_fence(raw: str) -> str:
    """Return the body of the first markdown code fence, or ``raw`` unchanged."""
    match = _FENCE_RE.search(raw)
    return match.group(1) if match else raw


def _first_json_array(text: str) -> str | None:
    """Extract the first balanced ``[...]`` substring, or ``None`` (string-aware)."""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _decode_array(raw: str) -> list[object] | None:
    """Decode ``raw`` into a JSON list, recovering from reasoning-model wrapping."""
    candidates = [raw, _strip_code_fence(raw)]
    array = _first_json_array(raw)
    if array is not None:
        candidates.append(array)
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(decoded, list):
            return decoded
    return None


def _parse_plan(raw: str) -> list[tuple[str, str, list[str], bool]]:
    """Parse the model's JSON array into ``(local_id, summary, deps, external)`` items.

    Tolerant (best-effort): markdown fences / a reasoning preamble / trailing text
    are stripped first; a non-array, a non-object entry, or a blank summary yields
    no item. A missing/false ``needs_external_agency`` defaults to ``False`` (the
    SAFE default — a task is treated as autonomous-safe unless flagged external).
    """
    decoded = _decode_array(raw)
    if decoded is None:
        logger.debug("Planner returned no parseable JSON array; empty plan")
        return []
    items: list[tuple[str, str, list[str], bool]] = []
    for position, entry in enumerate(decoded):
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        local = entry.get("id")
        local_id = local if isinstance(local, str) and local else f"_{position}"
        items.append(
            (local_id, summary.strip(), _parse_deps(entry.get("deps")), _parse_external(entry))
        )
    return items


def _parse_deps(raw: object) -> list[str]:
    """Parse the ``deps`` field into a list of string predecessor ids (lenient)."""
    if not isinstance(raw, list):
        return []
    return [dep for dep in raw if isinstance(dep, str) and dep]


def _parse_external(entry: dict[str, object]) -> bool:
    """Parse ``needs_external_agency`` — only an explicit truthy ``True`` flags it."""
    return entry.get("needs_external_agency") is True
