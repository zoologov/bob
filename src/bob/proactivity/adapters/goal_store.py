# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=infrastructure

"""SqliteGoalStore — the per-persona goal-graph adapter (Goal Engine, BOB-015).

Realises :class:`bob.proactivity.ports.GoalStore` over the ``goal`` and ``task`` tables:
one row per ``(persona_id, id)`` so Bobiverse replicas each keep their own goals
between sessions. The domain :class:`~bob.proactivity.goals.graph.GoalGraph` (its
:class:`~bob.proactivity.goals.entities.Goal` / :class:`~bob.proactivity.goals.entities.Task`
value objects, the enum states, the ``deps`` and ``needs_external_agency`` flags) is
mapped to and from rows here, so the domain stays I/O-free.

``deps`` round-trips as a JSON array (the readiness topo-sort is built from it, so a
separate edge table is unnecessary at MVP scale); the enum values persist as their
string ``.value`` (TEXT columns). ``save_goal`` / ``save_task`` UPSERT on the
composite key, and ``update_goal_state`` / ``update_task_state`` are atomic single-
column writes the approval use-case (.2) and the self-directed tick (.3) drive. An
unseen persona has no rows, so :meth:`load` returns an empty graph. All SQL is
parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.proactivity.goals.entities import Goal, GoalOrigin, Task
from bob.proactivity.goals.graph import GoalGraph
from bob.proactivity.goals.state import GoalState, TaskState

if TYPE_CHECKING:
    import aiosqlite


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteGoalStore:
    """SQLite adapter for Bob's per-persona goal graph (Goal Engine, BOB-015)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str) -> GoalGraph:
        """Return the persisted goal graph for ``persona_id`` (empty if unseen)."""
        goals = await self._load_goals(persona_id)
        tasks = await self._load_tasks(persona_id)
        return GoalGraph(goals=goals, tasks=tasks)

    async def save_goal(self, persona_id: str, goal: Goal) -> None:
        """Persist ``goal`` for ``persona_id`` — UPSERT on ``(persona_id, id)``."""
        await self._db().execute(
            "INSERT INTO goal "
            "(persona_id, id, title, description, priority, criteria, state, "
            "origin, created_at, deadline) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, id) DO UPDATE SET "
            "title = excluded.title, "
            "description = excluded.description, "
            "priority = excluded.priority, "
            "criteria = excluded.criteria, "
            "state = excluded.state, "
            "origin = excluded.origin, "
            "created_at = excluded.created_at, "
            "deadline = excluded.deadline",
            (
                persona_id,
                goal.id,
                goal.title,
                goal.description,
                goal.priority,
                goal.criteria,
                goal.state.value,
                goal.origin.value,
                goal.created_at.isoformat(),
                _format_ts(goal.deadline),
            ),
        )
        await self._db().commit()

    async def save_task(self, persona_id: str, task: Task) -> None:
        """Persist ``task`` for ``persona_id`` — UPSERT on ``(persona_id, id)``."""
        await self._db().execute(
            "INSERT INTO task "
            "(persona_id, id, goal_id, summary, deps, state, needs_external_agency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, id) DO UPDATE SET "
            "goal_id = excluded.goal_id, "
            "summary = excluded.summary, "
            "deps = excluded.deps, "
            "state = excluded.state, "
            "needs_external_agency = excluded.needs_external_agency",
            (
                persona_id,
                task.id,
                task.goal_id,
                task.summary,
                json.dumps(list(task.deps)),
                task.state.value,
                int(task.needs_external_agency),
            ),
        )
        await self._db().commit()

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None:
        """Atomically set ``goal_id``'s state for ``persona_id``."""
        await self._db().execute(
            "UPDATE goal SET state = ? WHERE persona_id = ? AND id = ?",
            (state.value, persona_id, goal_id),
        )
        await self._db().commit()

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:
        """Atomically set ``task_id``'s state for ``persona_id``."""
        await self._db().execute(
            "UPDATE task SET state = ? WHERE persona_id = ? AND id = ?",
            (state.value, persona_id, task_id),
        )
        await self._db().commit()

    async def _load_goals(self, persona_id: str) -> tuple[Goal, ...]:
        async with self._db().execute(
            "SELECT id, title, description, priority, criteria, state, origin, "
            "created_at, deadline FROM goal WHERE persona_id = ? "
            "ORDER BY created_at, id",
            (persona_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_goal(row) for row in rows)

    async def _load_tasks(self, persona_id: str) -> tuple[Task, ...]:
        async with self._db().execute(
            "SELECT id, goal_id, summary, deps, state, needs_external_agency "
            "FROM task WHERE persona_id = ? ORDER BY id",
            (persona_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_task(row) for row in rows)

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _row_to_goal(row: aiosqlite.Row) -> Goal:
    """Map a ``goal`` row back to its domain :class:`Goal`."""
    return Goal(
        id=str(row[0]),
        title=str(row[1]),
        description=str(row[2]),
        priority=int(row[3]),
        criteria=str(row[4]),
        state=GoalState(str(row[5])),
        origin=GoalOrigin(str(row[6])),
        created_at=datetime.fromisoformat(str(row[7])),
        deadline=_parse_ts(row[8]),
    )


def _row_to_task(row: aiosqlite.Row) -> Task:
    """Map a ``task`` row back to its domain :class:`Task` (deps decoded from JSON)."""
    raw_deps = json.loads(str(row[3]))
    return Task(
        id=str(row[0]),
        goal_id=str(row[1]),
        summary=str(row[2]),
        deps=tuple(str(dep) for dep in raw_deps),
        state=TaskState(str(row[4])),
        needs_external_agency=bool(row[5]),
    )


def _format_ts(value: datetime | None) -> str | None:
    """Render a timezone-aware datetime as ISO-8601 text (``None`` passes through)."""
    return None if value is None else value.isoformat()


def _parse_ts(raw: object) -> datetime | None:
    """Parse an ISO-8601 text marker back into a datetime (``None`` passes through)."""
    return None if raw is None else datetime.fromisoformat(str(raw))
