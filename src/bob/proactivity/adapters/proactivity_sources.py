# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=infrastructure

"""RepoProactivitySources — the live read-seams the proactivity engine reads.

The :class:`~bob.proactivity.usecases.engine.ProactivityEngine` needs two cheap
(no-LLM) signals on every heartbeat tick, both read straight off the live
``episodic_log``:

* **Reflection salience** (:class:`~bob.proactivity.usecases.engine.ReflectionSalienceSource`)
  — how striking Bob's most recent reflection is right now. A fresh ``reflection``
  episode (written by the heartbeat reflect tick) yields a salience near ``1.0``
  that decays linearly toward ``0.0`` over a fixed horizon, so a thought he just
  had pulls harder on the urge than a stale one, and no reflection at all scores
  ``0.0``.
* **Proactive window count**
  (:class:`~bob.proactivity.usecases.engine.ProactiveWindowCounter`) — how many
  ``proactive`` episodes lie inside the anti-spam window before ``now`` (the
  ceiling governance checks). Counted with parameterised SQL over the timestamp
  column — never an f-string.

Time is injected via :class:`~bob.domain.ports.Clock` so the salience decay is
deterministic in tests. The engine stays pure of storage; this adapter is the only
place these signals touch SQLite.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import aiosqlite

    from bob.kernel.ports import Clock

# A reflection at most this fresh scores full salience; older ones decay linearly
# to zero by this horizon. Tuned so a thought from the last reflect tick is vivid.
_SALIENCE_HORIZON = timedelta(hours=6)

# Proactive messages within this window before "now" count against the anti-spam
# ceiling. A day-long window matches the small per-day ceiling in Governance.
_WINDOW = timedelta(hours=24)

# The episode kinds the read-seams count off the episodic log.
_REFLECTION = "reflection"
_PROACTIVE = "proactive"
# Each autonomous goal advance (BOB-015 .3) writes a ``goal_progress`` episode; the
# self-directed tick reads them back to cap advances per window (a rate-limit on top
# of the governance ceiling).
_GOAL_PROGRESS = "goal_progress"

# The inner-life episode kinds the leak seam reads (BOB-018): both are REAL,
# grounded, persona-language reflections written by BOB-012's heartbeat ticks.
_INNER_LIFE_KINDS = ("reflection", "inner_monologue")


class _ConnectionProvider(Protocol):
    """The connection seam these read-seams need (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class _SystemClock:
    """Fallback UTC clock used when no clock is injected (production wiring injects one)."""

    def now(self) -> datetime:
        from datetime import UTC  # noqa: PLC0415 — local import keeps the module import-light

        return datetime.now(tz=UTC)


class RepoProactivitySources:
    """Back the engine's reflection-salience + proactive-window seams off SQLite.

    Also realises :class:`~bob.domain.ports.ReflectionReader` (BOB-018): the same
    reflection rows that drive proactivity salience supply the most-recent REAL
    reflection text the reactive reply path leaks into Bob's voice when the
    expression plan sets ``leak_inner_life`` (no reflection → ``None`` → no-op).
    """

    def __init__(
        self, repo: _ConnectionProvider, *, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._clock: Clock = clock if clock is not None else _SystemClock()

    async def latest_salience(self) -> float:
        """Return the recency-weighted salience of the latest reflection ([0, 1])."""
        marker = await self._latest_reflection_ts()
        if marker is None:
            return 0.0
        age = (self._clock.now() - marker).total_seconds()
        horizon = _SALIENCE_HORIZON.total_seconds()
        if age <= 0.0:
            return 1.0
        if age >= horizon:
            return 0.0
        return 1.0 - age / horizon

    async def proactive_count_in_window(self, *, now: datetime) -> int:
        """Count ``proactive`` episodes whose timestamp lies within the window before ``now``."""
        cutoff = (now - _WINDOW).isoformat()
        async with self._db().execute(
            "SELECT COUNT(*) FROM episodic_log "
            "WHERE event_type = ? AND ts >= ?",
            (_PROACTIVE, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def progress_count_in_window(self, *, now: datetime) -> int:
        """Count ``goal_progress`` episodes within the window before ``now``.

        The per-window task ceiling the self-directed tick (BOB-015 .3) enforces on
        top of governance — read with parameterised SQL over the timestamp column,
        the same machinery as the proactive-window count.
        """
        cutoff = (now - _WINDOW).isoformat()
        async with self._db().execute(
            "SELECT COUNT(*) FROM episodic_log WHERE event_type = ? AND ts >= ?",
            (_GOAL_PROGRESS, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def latest_reflection_text(self) -> str | None:
        """Return the most recent REAL reflection's text, or ``None`` if there is none.

        Realises :class:`~bob.domain.ports.ReflectionReader` (the BOB-018 leak seam):
        reads the newest ``episodic_log`` row whose ``event_type`` is a real
        inner-life kind (``reflection`` / ``inner_monologue``, written grounded and
        in the persona language by BOB-012). ``None`` means there is nothing real to
        leak, so the caller no-ops — never a fabrication. Parameterised SQL only.
        """
        placeholders = ", ".join("?" for _ in _INNER_LIFE_KINDS)
        async with self._db().execute(
            "SELECT content FROM episodic_log "  # noqa: S608 — placeholders are static "?" only
            f"WHERE event_type IN ({placeholders}) ORDER BY ts DESC, id DESC LIMIT 1",
            _INNER_LIFE_KINDS,
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        content = str(row[0]).strip()
        return content or None

    async def _latest_reflection_ts(self) -> datetime | None:
        """Return the timestamp of the most recent reflection episode, or ``None``."""
        async with self._db().execute(
            "SELECT ts FROM episodic_log "
            "WHERE event_type = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (_REFLECTION,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else datetime.fromisoformat(str(row[0]))

    def _db(self) -> aiosqlite.Connection:
        return self._repo.connection
