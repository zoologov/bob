# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=application

"""PursueGoalsTick — Bob продвигает СВОИ цели сам, под теми же воротами (BOB-015 .3).

Самонаправленный heartbeat-тик — автономность-стадия B. Он НЕ заводит новой
машинерии безопасности: идёт через те же ворота, что и проактивный чат
(:class:`~bob.proactivity.governance.Governance` + kill-switch), и опирается
на чистый домен Goal Engine (:func:`~bob.proactivity.goals.graph.next_safe_task`,
который сам исключает неутверждённые цели и внешне-агентные задачи). Порядок одного
тика — СТРОГО (safety-инварианты под тестами .4, ревью .5):

1. **Гейт (первым, до любой работы):** kill-switch
   (:meth:`PursuitStore.is_pursuit_stopped`) → если стоп, тик ничего не делает.
   Иначе :meth:`Governance.allows` (та же машина: quiet-hours / owner-mute /
   cooldown / per-window ceiling) над инъектированным часом и снимком истории —
   не разрешено → тик ничего не делает (ZERO работы).
2. **Выбор задачи:** ``graph = await goal_store.load(persona_id)`` →
   :func:`next_safe_task`. Домен гарантирует: только ``APPROVED`` / ``ACTIVE``
   цели, состояние ``NEW`` / ``READY``, deps ``DONE``, БЕЗ
   ``needs_external_agency``. Нет задачи → опционально вынести
   :func:`external_agency_tasks` как ПРЕДЛОЖЕНИЕ owner (стадия-C гейт), затем
   выход.
3. **Исполнение ТОЛЬКО безопасного шага:** задача ``READY`` → ``IN_PROGRESS``
   (через :func:`can_transition_task`), затем шаг исполняется ИСКЛЮЧИТЕЛЬНО через
   capability из safe-allowlist (:class:`SafeDispatcher` держит лишь безопасный
   под-набор реестра — capability вне allowlist в этом пути физически недоступны).
   Никакого исполнения внешне-агентных действий.
4. **Состояние + критерий + прозрачность:** задача → ``DONE`` (или ``BLOCKED`` с
   blocked_reason при неуспехе); если :func:`is_goal_complete` — цель ``ACTIVE`` →
   ``DONE``; записать ЭПИЗОД (память) И отправить owner короткое прогресс-сообщение
   («занялся X — сделал Y», кратко по BOB-024).
5. **Rate-limit:** не больше ``max_tasks_per_window`` продвинутых задач за окно
   (поверх governance-ceiling), считается по эпизодам ``goal_progress``.

Всё инъектируется (порты, Clock, seeded-RNG), так что тик детерминирован в тестах и
не держит ни глобалов, ни транспорта, ни конфига.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.memory.entities import EpisodicEvent
from bob.proactivity.goals.graph import (
    external_agency_tasks,
    is_goal_complete,
    next_safe_task,
)
from bob.proactivity.goals.state import GoalState, TaskState, can_transition, can_transition_task
from bob.proactivity.governance import ProactiveHistory

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from random import Random

    from bob.kernel.ports import Clock, ReplyGateway
    from bob.personality.state import PersonalityState
    from bob.proactivity.goals.entities import Goal, Task
    from bob.proactivity.goals.graph import GoalGraph
    from bob.proactivity.governance import Governance

logger = logging.getLogger(__name__)

__all__ = [
    "EpisodeWriter",
    "GoalStoreLike",
    "HistorySource",
    "ProgressWindowCounter",
    "PursueGoalsTick",
    "PursuitStore",
    "SafeDispatcher",
]

# Event type stamped on the episode each autonomous advance writes. The window
# counter reads it back to enforce the per-window task ceiling (a rate-limit ON
# TOP of the governance ceiling), and it gives Bob a recallable trail of what he
# did unprompted (transparency).
_PROGRESS_EVENT = "goal_progress"


class PursuitStore(Protocol):
    """Read seam for the kill-switch: ``/goals stop`` silences pursuit instantly.

    Realised by :class:`~bob.infrastructure.persistence.SqliteProactivityStore`:
    ``is_pursuit_stopped`` reads the persisted owner flag the tick checks FIRST,
    before any work. ``True`` → the tick does nothing this cycle.
    """

    async def is_pursuit_stopped(self, persona_id: str) -> bool:
        """Return whether the goal-pursuit kill-switch is set for ``persona_id``."""
        ...


class HistorySource(Protocol):
    """Read seam supplying the governance history snapshot (markers + owner-mute).

    Realised by :class:`~bob.infrastructure.persistence.SqliteProactivityStore`:
    the SAME per-persona proactivity state the proactive chat reasons over, so the
    self-directed tick honours the same quiet-hours / cooldown / owner-mute gates.
    """

    async def load(self, persona_id: str) -> _ProactivityStateLike: ...


class ProgressWindowCounter(Protocol):
    """Read seam: how many goal-progress advances happened in the current window.

    Realised over the episodic log (a ``goal_progress`` episode per autonomous
    advance), so the tick can cap advances at ``max_tasks_per_window`` — a
    rate-limit ON TOP of the governance per-window ceiling.
    """

    async def progress_count_in_window(self, *, now: datetime) -> int:
        """Return the count of goal-progress advances within the window at ``now``."""
        ...


class SafeDispatcher(Protocol):
    """Execute seam: run ONLY a safe-allowlist capability (GUPPI executes).

    The autonomous path's hard boundary: this dispatcher exposes EXCLUSIVELY the
    safe-allowlist subset of capabilities (recall/search memory, a note, a
    reflection, a progress message). External-agency or arbitrary capabilities are
    NEVER reachable here — they are simply not registered — so a self-directed tick
    cannot escalate to stage C by construction. :meth:`allows` lets the tick pick a
    capability it may run; :meth:`dispatch` runs it.
    """

    def allows(self, name: str) -> bool:
        """Whether ``name`` is in the safe-allowlist (runnable autonomously)."""
        ...

    async def dispatch(self, name: str, args: Mapping[str, object]) -> object:
        """Run the named safe capability against ``args`` (raises if not allowed)."""
        ...


class EpisodeWriter(Protocol):
    """Persistence seam: append the autonomous advance to episodic memory.

    A subset of :class:`~bob.memory.ports.MemoryRepo`: each advance is logged so it
    enters recall + recent-history (Bob can reference / explain what he did) and
    backs the per-window rate-limit count.
    """

    async def save_episode(self, episode: Mapping[str, object]) -> None: ...


class GoalStoreLike(Protocol):
    """The GoalStore surface the tick needs: load + atomic state moves.

    A subset of :class:`~bob.proactivity.ports.GoalStore`: the tick reads the graph and
    atomically advances exactly one safe task (and, on completion, its goal). It
    never creates goals/tasks here — it only moves an ALREADY-APPROVED goal forward,
    keeping the authz-before-autonomy machine honest.
    """

    async def load(self, persona_id: str) -> GoalGraph: ...
    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None: ...
    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None: ...


class _ProactivityStateLike(Protocol):
    """The fields the tick reads off the proactivity state for the history snapshot."""

    @property
    def last_spoke_at(self) -> datetime | None: ...
    @property
    def last_user_msg_at(self) -> datetime | None: ...
    @property
    def proactivity_enabled(self) -> bool: ...


class PursueGoalsTick:
    """Advance one APPROVED goal a safe step, under the proactive-chat gates."""

    def __init__(
        self,
        *,
        persona_id: str,
        chat_id: int,
        goal_store: GoalStoreLike,
        pursuit_store: PursuitStore,
        governance: Governance,
        history: HistorySource,
        window: ProgressWindowCounter,
        dispatcher: SafeDispatcher,
        episodes: EpisodeWriter,
        gateway: ReplyGateway,
        personality: PersonalityState,
        clock: Clock,
        rng: Random,
        safe_capabilities: tuple[str, ...] = (),
        max_tasks_per_window: int = 1,
    ) -> None:
        self._persona_id = persona_id
        self._chat_id = chat_id
        self._goal_store = goal_store
        self._pursuit_store = pursuit_store
        self._governance = governance
        self._history = history
        self._window = window
        self._dispatcher = dispatcher
        self._episodes = episodes
        self._gateway = gateway
        self._personality = personality
        self._clock = clock
        # A seeded RNG: when several safe capabilities are allowed the choice is
        # deterministic-by-seed (reproducible in tests), NOT cryptographic.
        self._rng = rng
        # The configured safe-allowlist preference order; only names the dispatcher
        # ALSO allows are ever run (the dispatcher is the hard boundary, this is the
        # preference among what is safe).
        self._safe_capabilities = safe_capabilities
        self._max_tasks_per_window = max_tasks_per_window

    async def run(self) -> None:
        """Run one self-directed pursuit cycle (gates first; default no-op)."""
        now = self._clock.now()
        if not await self._gate_open(now):
            return
        if await self._window.progress_count_in_window(now=now) >= self._max_tasks_per_window:
            logger.debug("pursue tick: per-window task ceiling reached; skipping")
            return

        graph = await self._goal_store.load(self._persona_id)
        task = next_safe_task(graph)
        if task is None:
            await self._maybe_propose_external(graph)
            return

        await self._advance(graph, task, now)

    async def _gate_open(self, now: datetime) -> bool:
        """Kill-switch FIRST, then the governance veto — both before any work.

        ``True`` only when pursuit is not stopped AND governance permits (the SAME
        machine the proactive chat uses: quiet-hours / owner-mute / cooldown /
        per-window ceiling). A veto or a set kill-switch ends the tick doing nothing.
        """
        if await self._pursuit_store.is_pursuit_stopped(self._persona_id):
            logger.debug("pursue tick: kill-switch set; doing nothing")
            return False
        history = await self._build_history(now)
        if not self._governance.allows(now=now, history=history):
            logger.debug("pursue tick: governance veto; doing nothing")
            return False
        return True

    async def _build_history(self, now: datetime) -> ProactiveHistory:
        """Build the governance history snapshot off the shared proactivity state."""
        state = await self._history.load(self._persona_id)
        return ProactiveHistory(
            last_spoke_at=state.last_spoke_at,
            last_user_msg_at=state.last_user_msg_at,
            sent_in_window=await self._window.progress_count_in_window(now=now),
            muted=not state.proactivity_enabled,
        )

    async def _advance(self, graph: GoalGraph, task: Task, now: datetime) -> None:
        """Execute one safe step for ``task``, then update state + tell the owner."""
        goal = graph.goal_by_id(task.goal_id)
        if goal is None:  # pragma: no cover - next_safe_task guarantees a pursuable goal
            return
        await self._goal_store.update_task_state(
            self._persona_id, task.id, TaskState.IN_PROGRESS
        )
        outcome = await self._execute_safe_step(task)
        if outcome is None:
            await self._block(task, "не нашлось безопасного шага (нет allowlist-capability)")
            return
        await self._goal_store.update_task_state(self._persona_id, task.id, TaskState.DONE)
        await self._complete_goal_if_done(goal)
        await self._remember(task, goal, now)
        await self._notify_owner(_progress_message(goal, task))

    async def _execute_safe_step(self, task: Task) -> object | None:
        """Run ONE safe-allowlist capability for ``task``; ``None`` if none is runnable.

        Iterates the configured allowlist (seeded order) and runs the first
        capability the dispatcher ALSO allows. Because the dispatcher only ever
        exposes safe capabilities, an external-agency or arbitrary capability is
        unreachable here by construction. A dispatch failure is swallowed to a
        ``None`` (→ the task is BLOCKED), never an escalation.
        """
        for name in self._allowlist_order():
            if not self._dispatcher.allows(name):
                continue
            try:
                return await self._dispatcher.dispatch(name, {"query": task.summary})
            except Exception:
                logger.exception("pursue tick: safe capability %s failed", name)
                return None
        return None

    def _allowlist_order(self) -> tuple[str, ...]:
        """The safe-allowlist in a seeded order (deterministic given the seed)."""
        names = list(self._safe_capabilities)
        self._rng.shuffle(names)
        return tuple(names)

    async def _block(self, task: Task, reason: str) -> None:
        """Move the in-progress task to BLOCKED (a stuck step is visible, not silent)."""
        if can_transition_task(TaskState.IN_PROGRESS, TaskState.BLOCKED):
            await self._goal_store.update_task_state(
                self._persona_id, task.id, TaskState.BLOCKED
            )
        logger.info("pursue tick: task %s blocked: %s", task.id, reason)

    async def _complete_goal_if_done(self, goal: Goal) -> None:
        """If every non-skipped task is now DONE, move the goal ACTIVE → DONE.

        Re-loads the graph AFTER this cycle's task-DONE write, so the structural
        check (:func:`is_goal_complete`) sees the just-advanced task as done and
        completion is recognised on the same tick. Only a legal ACTIVE → DONE
        transition is taken (the criterion text is the owner's call; the structural
        predicate is the gate here).
        """
        fresh = await self._goal_store.load(self._persona_id)
        if not is_goal_complete(goal, fresh.tasks_of(goal.id)):
            return
        if not can_transition(goal.state, GoalState.DONE):
            return
        await self._goal_store.update_goal_state(self._persona_id, goal.id, GoalState.DONE)
        logger.info("pursue tick: goal %s complete", goal.id)

    async def _maybe_propose_external(self, graph: GoalGraph) -> None:
        """Surface a ready external-agency task to the owner as a PROPOSAL (not auto).

        ``needs_external_agency`` tasks are NEVER executed autonomously — when there
        is no safe task to run, the tick may instead OFFER the owner the stage-C gate
        ("для этого нужен код/инструмент — запустить?"). Offering only; no execution.
        """
        candidates = external_agency_tasks(graph)
        if not candidates:
            return
        task = candidates[0]
        await self._notify_owner(_external_proposal_message(task))

    async def _remember(self, task: Task, goal: Goal, now: datetime) -> None:
        """Append the autonomous advance to episodic memory (transparency + recall)."""
        episode = EpisodicEvent(
            ts=now,
            event_type=_PROGRESS_EVENT,
            content=f"bob (goal): продвинул «{goal.title}» — {task.summary}",
            mood_snapshot=self._personality.soul.mood.tone(),
            tags=("goal", "autonomous"),
        )
        await self._episodes.save_episode(
            {
                "ts": episode.ts.isoformat(),
                "event_type": episode.event_type,
                "content": episode.content,
                "mood_snapshot": episode.mood_snapshot,
                "tags": ",".join(episode.tags),
            }
        )

    async def _notify_owner(self, message: str) -> None:
        """Post a short progress / proposal message into Bob's topic (best-effort)."""
        async with self._gateway.typing_indicator(chat_id=self._chat_id):
            pass
        await self._gateway.reply(chat_id=self._chat_id, markdown=message)


def _progress_message(goal: Goal, task: Task) -> str:
    """Render the short owner-facing progress note (BOB-024: terse, in Bob's voice)."""
    return f"Занялся целью «{goal.title}» — сделал: {task.summary}."


def _external_proposal_message(task: Task) -> str:
    """Render the owner-facing stage-C proposal for an external-agency task."""
    return (
        f"Для шага «{task.summary}» нужен код или внешний инструмент "
        "(стадия C, отдельный гейт). Запустить?"
    )
