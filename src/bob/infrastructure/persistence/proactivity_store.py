# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SqliteProactivityStore — the per-persona proactivity state adapter.

Realises :class:`bob.domain.ports.ProactivityStore` over the ``proactivity_state``
table: one row per ``persona_id`` so Bobiverse replicas each keep their own
reservoir, markers, and owner-mute flag. The domain
:class:`~bob.domain.proactivity.state.ProactivityState` is mapped to and from a
row here (the energy reservoir as a REAL, the markers as nullable ISO-8601 text,
the flag as 0/1) so the domain stays I/O-free.

On top of the port it exposes an infrastructure-level ``mute_until`` timed-mute
expiry (set by ``/quiet 2h``): it is *not* part of the domain state value object,
so it lives only in the row and is read/written via :meth:`get_mute_until` /
:meth:`set_mute_until`. All SQL is parameterised (``?``) — never an f-string.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from bob.domain.proactivity.social_energy import SocialEnergy
from bob.domain.proactivity.state import ProactivityState

if TYPE_CHECKING:
    import aiosqlite

# A fresh persona starts with an empty reservoir, no markers, and proactivity on.
_DEFAULT_STATE = ProactivityState(
    social_energy=SocialEnergy(0.0),
    last_spoke_at=None,
    last_user_msg_at=None,
    proactivity_enabled=True,
)


class _ConnectionProvider(Protocol):
    """The connection seam the store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class SqliteProactivityStore:
    """SQLite adapter for the per-persona proactivity state (drive engine)."""

    def __init__(self, repo: _ConnectionProvider) -> None:
        self._repo = repo

    async def load(self, persona_id: str) -> ProactivityState:
        """Return the persisted proactivity state for ``persona_id``.

        An unseen persona yields the default state (empty reservoir, no markers,
        proactivity enabled) so the engine always has something to read.
        """
        async with self._db().execute(
            "SELECT social_energy, last_spoke_at, last_user_msg_at, proactivity_enabled "
            "FROM proactivity_state WHERE persona_id = ?",
            (persona_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return _DEFAULT_STATE
        return ProactivityState(
            social_energy=SocialEnergy(float(row[0])),
            last_spoke_at=_parse_ts(row[1]),
            last_user_msg_at=_parse_ts(row[2]),
            proactivity_enabled=bool(row[3]),
        )

    async def save(self, persona_id: str, state: ProactivityState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior state).

        Upserts the domain columns only; the infrastructure-level ``mute_until``
        column is left untouched so a state write never clears a timed mute.
        """
        await self._db().execute(
            "INSERT INTO proactivity_state "
            "(persona_id, social_energy, last_spoke_at, last_user_msg_at, proactivity_enabled) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id) DO UPDATE SET "
            "social_energy = excluded.social_energy, "
            "last_spoke_at = excluded.last_spoke_at, "
            "last_user_msg_at = excluded.last_user_msg_at, "
            "proactivity_enabled = excluded.proactivity_enabled",
            (
                persona_id,
                state.social_energy.level,
                _format_ts(state.last_spoke_at),
                _format_ts(state.last_user_msg_at),
                int(state.proactivity_enabled),
            ),
        )
        await self._db().commit()

    async def get_mute_until(self, persona_id: str) -> datetime | None:
        """Return the timed-mute expiry for ``persona_id``, or ``None`` if unset."""
        async with self._db().execute(
            "SELECT mute_until FROM proactivity_state WHERE persona_id = ?",
            (persona_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _parse_ts(row[0])

    async def set_mute_until(self, persona_id: str, until: datetime | None) -> None:
        """Set (or clear, with ``None``) the timed-mute expiry for ``persona_id``.

        Upserts on ``persona_id`` so the expiry can be set before any domain state
        exists; a new row defaults the other columns to the schema defaults.
        """
        await self._db().execute(
            "INSERT INTO proactivity_state (persona_id, social_energy, mute_until) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(persona_id) DO UPDATE SET mute_until = excluded.mute_until",
            (persona_id, _DEFAULT_STATE.social_energy.level, _format_ts(until)),
        )
        await self._db().commit()

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection


def _format_ts(value: datetime | None) -> str | None:
    """Render a timezone-aware datetime as ISO-8601 text (``None`` passes through)."""
    return None if value is None else value.isoformat()


def _parse_ts(raw: object) -> datetime | None:
    """Parse an ISO-8601 text marker back into a datetime (``None`` passes through)."""
    return None if raw is None else datetime.fromisoformat(str(raw))
