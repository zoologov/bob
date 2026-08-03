# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""SqliteCodingSessionStore — durable store for gated coding sessions (BOB-039 .1).

Realises :class:`bob.coding.ports.CodingSessionStore` over the ``coding_session``
table: one row per session ``id``. The domain
:class:`~bob.coding.entities.CodingSession` (its
:class:`~bob.coding.state.CodingSessionState`, branch, worktree path, plan and
PR url) is mapped to and from rows here, so the domain stays I/O-free. ``save`` UPSERTs
on the ``id`` (a session advances, so each step re-saves the newer state), ``get``
returns ``None`` for an unknown id, and ``active`` lists the non-terminal sessions
(oldest first) so the use-case can find the in-flight one. All SQL is parameterised
(``?``) — never an f-string.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteCodingSessionStore:
    """SQLite adapter for Bob's gated coding sessions (BOB-039)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def save(self, session: CodingSession) -> None:
        """Persist ``session`` — UPSERT on ``id``."""
        await self._db().execute(
            "INSERT INTO coding_session "
            "(id, task, state, branch, created_at, updated_at, "
            "worktree_path, plan, pr_url, claude_session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "task = excluded.task, "
            "state = excluded.state, "
            "branch = excluded.branch, "
            "created_at = excluded.created_at, "
            "updated_at = excluded.updated_at, "
            "worktree_path = excluded.worktree_path, "
            "plan = excluded.plan, "
            "pr_url = excluded.pr_url, "
            "claude_session_id = excluded.claude_session_id",
            (
                session.id,
                session.task,
                session.state.value,
                session.branch,
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                session.worktree_path,
                session.plan,
                session.pr_url,
                session.claude_session_id,
            ),
        )
        await self._db().commit()

    async def get(self, session_id: str) -> CodingSession | None:
        """Return the session with ``session_id``, or ``None`` if there is none."""
        async with self._db().execute(
            "SELECT id, task, state, branch, created_at, updated_at, "
            "worktree_path, plan, pr_url, claude_session_id "
            "FROM coding_session WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _row_to_session(row)

    async def active(self) -> tuple[CodingSession, ...]:
        """Return the non-terminal sessions (oldest first; empty when none).

        Non-terminal is filtered through the domain :func:`is_terminal` predicate —
        the single source of truth — so the store can never drift from the machine's
        notion of a still-in-flight session.
        """
        async with self._db().execute(
            "SELECT id, task, state, branch, created_at, updated_at, "
            "worktree_path, plan, pr_url, claude_session_id "
            "FROM coding_session ORDER BY created_at, id",
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(
            session
            for session in (_try_row_to_session(row) for row in rows)
            if session is not None and not is_terminal(session.state)
        )

    async def by_branch(self, branch: str) -> tuple[CodingSession, ...]:
        """Return every recorded session on ``branch`` (oldest first; empty when none).

        Realises the narrow :class:`bob.coding.ports.ResumableSessionLookup` read seam
        (BOB-087.D3). Unlike :meth:`active` it filters by BRANCH ONLY and keeps EVERY
        state, terminal included — deciding which of them may be resumed is the pure
        policy's job (:func:`bob.coding.resume_policy.select_resumable`), so the store
        cannot drift from the «only a stopped session may be raised» rule. The branch is
        bound as a parameter (``?``), never interpolated. One unparseable row is logged
        and SKIPPED (same resilience as :meth:`active`): a corrupt record must not blow
        up the owner's resume command.
        """
        async with self._db().execute(
            "SELECT id, task, state, branch, created_at, updated_at, "
            "worktree_path, plan, pr_url, claude_session_id "
            "FROM coding_session WHERE branch = ? ORDER BY created_at, id",
            (branch,),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(
            session
            for session in (_try_row_to_session(row) for row in rows)
            if session is not None
        )

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _try_row_to_session(row: aiosqlite.Row) -> CodingSession | None:
    """Map a row to its :class:`CodingSession`, or ``None`` if it cannot be parsed.

    🔴 Резилентность (BOB-078 D): ``active()`` дёргается coding-router'ом на КАЖДОМ
    входящем сообщении. ОДНА битая строка (напр. ``state`` вне ``CodingSessionState`` →
    ``ValueError``, или битая дата) НЕ должна ронять весь список — иначе роутер бросает на
    каждом сообщении и Боб глохнет. Битую строку логируем и ПРОПУСКАЕМ; валидные сессии
    возвращаются как обычно.
    """
    try:
        return _row_to_session(row)
    except (ValueError, TypeError):
        logger.exception(
            "coding_session: пропускаю неразбираемую строку id=%r state=%r",
            row[0],
            row[2],
        )
        return None


def _row_to_session(row: aiosqlite.Row) -> CodingSession:
    """Map a ``coding_session`` row back to its domain :class:`CodingSession`."""
    return CodingSession(
        id=str(row[0]),
        task=str(row[1]),
        state=CodingSessionState(str(row[2])),
        branch=str(row[3]),
        created_at=datetime.fromisoformat(str(row[4])),
        updated_at=datetime.fromisoformat(str(row[5])),
        worktree_path=_opt_str(row[6]),
        plan=_opt_str(row[7]),
        pr_url=_opt_str(row[8]),
        claude_session_id=_opt_str(row[9]),
    )


def _opt_str(value: object) -> str | None:
    """Return ``value`` as text, or ``None`` when the column is NULL."""
    return None if value is None else str(value)
