# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""Sulk source adapter — the live обида seam the turn + ticks read (BOB-014 .2b).

A thin application adapter that keeps :class:`HandleMessage` (and the recovery tick)
pure of store plumbing for Bob's обида state:

* :meth:`SulkTracker.current` LOADS the persisted
  :class:`~bob.social.sulk.SulkState` so the compose path can go cold
  while Bob is hurt and the proactivity engine can read the sulk veto.
* :meth:`SulkTracker.observe` folds ONE owner turn's signals into обида: while not
  sulking it runs the pure :func:`~bob.social.sulk.observe_relationship`
  (threshold + sustaining — a sustained critical owner-drop OR sustained directed
  hostility enters обида, never one bad message / casual мат); while ALREADY sulking a
  warm owner turn instead ACCELERATES recovery (тёплые сообщения), so the live message
  path warms Bob up. It persists the new state and, on a fresh ENTRY, announces обида
  exactly once via the optional :class:`SulkAnnouncer` seam (GUPPI).
* :meth:`SulkTracker.recover` decays обида by elapsed time on the reflect tick — the
  GUARANTEED exit (time alone brings Bob back, even with no warmth).

обида is per-PERSONA (keyed by ``persona_id``), like proactivity state, and carries NO
memory and NO soul (anti-Exodus). The thresholds/dynamics are injected so config can
tune them; defaults are the small domain defaults.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from bob.social.sulk import observe_relationship, recover

if TYPE_CHECKING:
    from datetime import datetime

    from bob.domain.ports import Clock, SulkStore
    from bob.social.sulk import SulkConfig, SulkState

logger = logging.getLogger(__name__)

__all__ = ["SulkAnnouncer", "SulkRecoveryStep", "SulkTracker"]


class SulkAnnouncer(Protocol):
    """The one-shot обида announce seam (BOB-014 .2b), realised by GUPPI.

    On a FRESH entry into обида GUPPI posts a single system line ("Боб обижен и сейчас
    не хочет разговаривать") into the chat the owner sees — the внеличностный systemic
    voice, NOT Bob himself. It fires exactly once per entry (the one-shot ``announced``
    flag on :class:`~bob.social.sulk.SulkState` guards repeats). Best-effort
    and optional: with no announcer wired the entry is silent and обида still takes hold.
    """

    async def announce_sulk(self) -> None:
        """Post the one-shot обида announcement (best-effort)."""
        ...


class SulkTracker:
    """Load + evolve + recover Bob's обида state (per persona, BOB-014 .2b)."""

    def __init__(
        self,
        *,
        store: SulkStore,
        persona_id: str,
        config: SulkConfig | None = None,
        announcer: SulkAnnouncer | None = None,
    ) -> None:
        self._store = store
        self._persona_id = persona_id
        self._config = config
        self._announcer = announcer

    async def current(self) -> SulkState:
        """Return Bob's current обида state (fresh/not-sulking if never hurt)."""
        return await self._store.load(self._persona_id)

    async def current_active(self) -> bool:
        """Return whether Bob is currently обижен (the proactivity sulk veto)."""
        return (await self._store.load(self._persona_id)).active

    async def observe(
        self,
        *,
        owner_warmth: float,
        hostile: bool,
        warmth_delta: float,
        now: datetime,
    ) -> SulkState:
        """Fold one OWNER turn into обида; announce once on a fresh entry (BOB-014 .2b).

        While NOT sulking the pure entry transition runs (threshold + sustaining: a
        sustained critical owner-drop OR sustained directed hostility enters обида,
        never one bad message / casual мат). While ALREADY sulking a warm owner turn
        (positive ``warmth_delta``) ACCELERATES recovery instead — the live message path
        warms Bob up faster than time alone. The new state is persisted; on a fresh
        ENTRY (was not active, now active) GUPPI announces обида exactly once. Returns
        the new state so the caller can thread it through this turn.
        """
        before = await self._store.load(self._persona_id)
        if before.active:
            # Already обижен: a warm turn accelerates отход; the guaranteed time-decay
            # exit is owned by the reflect-tick recover() path. Negative warmth here is
            # a no-op on intensity (it cannot deepen обида past the cap).
            after = recover(
                before, elapsed_seconds=0.0, warmth_delta=warmth_delta, config=self._config
            )
        else:
            after = observe_relationship(
                before,
                owner_warmth=owner_warmth,
                hostile=hostile,
                now=now,
                config=self._config,
            )
        if after.active and not before.active:
            # Fresh entry: announce обида exactly once and persist the one-shot flag so
            # a restart mid-обида cannot re-announce. recover() clears it again on exit.
            await self._announce_entry()
            after = replace(after, announced=True)
        await self._store.save(self._persona_id, after)
        return after

    async def recover(self, *, elapsed_seconds: float, now: datetime) -> SulkState:
        """Decay обида by elapsed time on the reflect tick — the GUARANTEED exit.

        Time alone brings Bob back (no warmth needed), so обида is never a permanent
        lock-out. A no-op when Bob is not hurt. Persists the decayed/exited state. The
        ``now`` is accepted for symmetry with the other seams; only the elapsed time
        drives the decay.
        """
        _ = now
        before = await self._store.load(self._persona_id)
        after = recover(before, elapsed_seconds=elapsed_seconds, config=self._config)
        if after != before:
            await self._store.save(self._persona_id, after)
        return after

    async def _announce_entry(self) -> None:
        """Announce a fresh обида entry once via GUPPI (best-effort, optional)."""
        if self._announcer is None:
            return
        try:
            await self._announcer.announce_sulk()
        except Exception:
            logger.exception("announcing sulk entry failed (ignored)")


class SulkRecoveryStep:
    """The reflect-tick обида recovery collaborator (BOB-014 .2b).

    A thin ``run()``-shaped step (matching the other reflect-tick evolvers) that decays
    обида by the REAL elapsed time since the last recovery tick — the GUARANTEED exit,
    since time alone brings Bob back. It stamps the clock on each run so the next tick
    decays the real gap; the first run (no prior stamp) only stamps and does not decay.
    Driven on the same slow cadence as the other reflect-tick steps. A no-op when Bob is
    not hurt, so an unwired/idle Bob behaves exactly as before.
    """

    def __init__(self, *, tracker: SulkTracker, clock: Clock) -> None:
        self._tracker = tracker
        self._clock = clock
        self._last_run_at: datetime | None = None

    async def run(self) -> None:
        """Decay обида by the elapsed time since the last recovery tick."""
        now = self._clock.now()
        last = self._last_run_at
        self._last_run_at = now
        if last is None:
            return
        elapsed = max(0.0, (now - last).total_seconds())
        await self._tracker.recover(elapsed_seconds=elapsed, now=now)
