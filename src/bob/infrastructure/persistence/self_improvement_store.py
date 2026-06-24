# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteSelfImprovementStore — the per-persona self-improvement-rule adapter (BOB-028 .1).

Realises :class:`bob.domain.ports.SelfImprovementStore` over the ``improvement_rule``
table: one row per ``(persona_id, id)`` so Bobiverse replicas each keep their own
curated rules between sessions. The domain
:class:`~bob.domain.personality.self_improvement.ImprovementRule` value object (its
:class:`~bob.domain.personality.self_improvement.Lever`,
:class:`~bob.domain.personality.self_improvement.RuleState` and
:class:`~bob.domain.personality.self_improvement.RuleOrigin` enums, the bounded
``magnitude``) is mapped to and from rows here, so the domain stays I/O-free.

The enum values persist as their string ``.value`` (TEXT columns). ``save_rule``
UPSERTs on the composite key, and ``update_rule_state`` is an atomic single-column
write the manage-rules use-case (.3) drives — only owner approval moves PROPOSED ->
APPROVED. An unseen persona has no rows, so :meth:`load` returns an empty tuple. All
SQL is parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.domain.personality.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)

if TYPE_CHECKING:
    import aiosqlite


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteSelfImprovementStore:
    """SQLite adapter for Bob's per-persona self-improvement rules (BOB-028 .1)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:
        """Return the persisted rules for ``persona_id`` (empty tuple if unseen)."""
        async with self._db().execute(
            "SELECT id, observation, adjustment, lever, magnitude, state, origin, "
            "created_at, evidence FROM improvement_rule WHERE persona_id = ? "
            "ORDER BY created_at, id",
            (persona_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return tuple(_row_to_rule(row) for row in rows)

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:
        """Persist ``rule`` for ``persona_id`` — UPSERT on ``(persona_id, id)``."""
        await self._db().execute(
            "INSERT INTO improvement_rule "
            "(persona_id, id, observation, adjustment, lever, magnitude, state, "
            "origin, created_at, evidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, id) DO UPDATE SET "
            "observation = excluded.observation, "
            "adjustment = excluded.adjustment, "
            "lever = excluded.lever, "
            "magnitude = excluded.magnitude, "
            "state = excluded.state, "
            "origin = excluded.origin, "
            "created_at = excluded.created_at, "
            "evidence = excluded.evidence",
            (
                persona_id,
                rule.id,
                rule.observation,
                rule.adjustment,
                rule.lever.value,
                rule.magnitude,
                rule.state.value,
                rule.origin.value,
                rule.created_at.isoformat(),
                rule.evidence,
            ),
        )
        await self._db().commit()

    async def update_rule_state(
        self, persona_id: str, rule_id: str, state: RuleState
    ) -> None:
        """Atomically set ``rule_id``'s state for ``persona_id``."""
        await self._db().execute(
            "UPDATE improvement_rule SET state = ? WHERE persona_id = ? AND id = ?",
            (state.value, persona_id, rule_id),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _row_to_rule(row: aiosqlite.Row) -> ImprovementRule:
    """Map an ``improvement_rule`` row back to its domain :class:`ImprovementRule`."""
    return ImprovementRule(
        id=str(row[0]),
        observation=str(row[1]),
        adjustment=str(row[2]),
        lever=Lever(str(row[3])),
        magnitude=float(row[4]),
        state=RuleState(str(row[5])),
        origin=RuleOrigin(str(row[6])),
        created_at=datetime.fromisoformat(str(row[7])),
        evidence=str(row[8]),
    )
