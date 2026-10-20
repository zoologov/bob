# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""Sulk source adapter — the live per-person обида seam (BOB-014 .2b, BOB-066 2.5).

A thin application adapter that keeps :class:`HandleMessage` (and the recovery tick)
pure of store plumbing for Bob's обида state, now keyed per ``(persona, sender)`` so Bob
can cool toward ONE participant of a multi-party thread without touching his tone toward
anyone else:

* :meth:`SulkTracker.current_for` LOADS the persisted
  :class:`~bob.kernel.sulk.SulkState` for ONE ``sender_id`` so the compose path can go
  cold for the CURRENT interlocutor (an обида on Лёша never chills a reply to Владимир).
* :meth:`SulkTracker.current_active` reads the OWNER's обида — the proactivity sulk veto
  (Bob does not write first while обижен at his person).
* :meth:`SulkTracker.observe` folds ONE person's turn into their обида: while not sulking
  it runs the pure :func:`~bob.social.sulk.observe_relationship` (threshold + sustaining —
  a sustained critical warmth-drop OR sustained directed hostility enters обида, never one
  bad message / casual мат); while ALREADY sulking a warm turn instead ACCELERATES
  recovery. It persists the new state and, on a fresh ENTRY, announces обида exactly once
  via the announcer — GUPPI in an owner-DM scope, a silent :class:`GroupSilentAnnouncer`
  in a group (the cold is read through the addressed tone, not a systemic line).
* :meth:`SulkTracker.active_targets` lists the senders Bob is CURRENTLY обижен at, and
  :meth:`SulkTracker.recover` decays each active обида by elapsed time on the reflect tick
  — the GUARANTEED exit (time alone brings Bob back, even with no warmth).

обида is per-``(persona_id, sender_id)`` and carries NO memory and NO soul (anti-Exodus).
The thresholds/dynamics are injected so config can tune them; defaults are the small
domain defaults.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from bob.social.sulk import observe_relationship, recover

if TYPE_CHECKING:
    from datetime import datetime

    from bob.kernel.ports import Clock
    from bob.kernel.sulk import SulkState
    from bob.social.ports import PersonSulkStore
    from bob.social.sulk import SulkConfig

logger = logging.getLogger(__name__)

__all__ = [
    "GroupSilentAnnouncer",
    "SulkAnnouncer",
    "SulkRecoveryStep",
    "SulkTracker",
]


class SulkAnnouncer(Protocol):
    """The one-shot обида announce seam (BOB-014 .2b), realised by GUPPI.

    On a FRESH entry into обида GUPPI posts a single system line ("Боб обижен и сейчас
    не хочет разговаривать") into the chat the owner sees — the внеличностный systemic
    voice, NOT Bob himself. It fires exactly once per entry (the one-shot ``announced``
    flag on :class:`~bob.kernel.sulk.SulkState` guards repeats). Best-effort
    and optional: with no announcer wired the entry is silent and обида still takes hold.
    """

    async def announce_sulk(self) -> None:
        """Post the one-shot обида announcement (best-effort)."""
        ...


class GroupSilentAnnouncer:
    """The scope-aware SILENT announcer for a group обида entry (BOB-066 2.5, Q4).

    In an owner-DM the fresh обида entry gets the systemic GUPPI line; in a GROUP that
    внеличностный system line would be jarring, so the entry is SILENT — Bob's cooling is
    read through the ADDRESSED tone toward that one participant, not a broadcast notice.
    The application injects this null-object announcer for a group-scoped
    :meth:`SulkTracker.observe`, so обида still takes hold (persisted, cold tone applied)
    while nothing is posted. A no-op by construction.
    """

    async def announce_sulk(self) -> None:
        """No-op: a group обида entry is silent (the cold reads through the tone)."""
        return None


class SulkTracker:
    """Load + evolve + recover Bob's per-person обида state (BOB-014 .2b, BOB-066 2.5)."""

    def __init__(
        self,
        *,
        store: PersonSulkStore,
        persona_id: str,
        owner_sender_id: int | None = None,
        config: SulkConfig | None = None,
        announcer: SulkAnnouncer | None = None,
    ) -> None:
        self._store = store
        self._persona_id = persona_id
        self._owner_sender_id = owner_sender_id
        self._config = config
        self._announcer = announcer

    async def current_for(self, sender_id: int) -> SulkState:
        """Return Bob's current обида state toward ``sender_id`` (fresh if never hurt)."""
        return await self._store.load(self._persona_id, sender_id)

    async def current_active(self) -> bool:
        """Return whether Bob is обижен at his OWNER (the proactivity sulk veto).

        Proactivity leads the OWNER relationship, so its veto reads the owner's обида;
        with no owner id wired it reads not-sulking (the veto is inert).
        """
        if self._owner_sender_id is None:
            return False
        return (await self._store.load(self._persona_id, self._owner_sender_id)).active

    async def observe(
        self,
        *,
        sender_id: int,
        person_warmth: float,
        hostile: bool,
        warmth_delta: float,
        now: datetime,
        announcer: SulkAnnouncer | None = None,
    ) -> SulkState:
        """Fold one person's turn into their обида; announce once on entry (BOB-066 2.5).

        While NOT sulking the pure entry transition runs (threshold + sustaining: a
        sustained critical warmth-drop OR sustained directed hostility enters обида, never
        one bad message / casual мат). While ALREADY sulking a warm turn (positive
        ``warmth_delta``) ACCELERATES recovery instead — the live message path warms Bob
        up faster than time alone. The new state is persisted per ``(persona, sender)``; on
        a fresh ENTRY (was not active, now active) обида is announced exactly once. An
        explicit ``announcer`` overrides the default (a group scope passes a
        :class:`GroupSilentAnnouncer` so the entry is silent — the cold reads through the
        addressed tone); omitted, the constructor's owner-DM GUPPI announcer is used.
        Returns the new state so the caller can thread it through this turn.
        """
        before = await self._store.load(self._persona_id, sender_id)
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
                person_warmth=person_warmth,
                hostile=hostile,
                now=now,
                config=self._config,
            )
        if after.active and not before.active:
            # Fresh entry: announce обида exactly once and persist the one-shot flag so
            # a restart mid-обида cannot re-announce. recover() clears it again on exit.
            await self._announce_entry(announcer if announcer is not None else self._announcer)
            after = replace(after, announced=True)
        await self._store.save(self._persona_id, sender_id, after)
        return after

    async def active_targets(self) -> list[int]:
        """Return the senders Bob is CURRENTLY обижен at (the recovery tick iterates these)."""
        return await self._store.active_sulks(self._persona_id)

    async def recover(self, *, elapsed_seconds: float, now: datetime) -> None:
        """Decay EACH active обида by elapsed time on the reflect tick — the GUARANTEED exit.

        Time alone brings Bob back (no warmth needed), so an обида is never a permanent
        lock-out. Iterates ONLY the currently-active senders (a not-sulking pair is never
        touched), persisting each decayed/exited state. A no-op when Bob is not hurt at
        anyone. The ``now`` is accepted for symmetry with the other seams; only the elapsed
        time drives the decay.
        """
        _ = now
        for sender_id in await self._store.active_sulks(self._persona_id):
            before = await self._store.load(self._persona_id, sender_id)
            after = recover(before, elapsed_seconds=elapsed_seconds, config=self._config)
            if after != before:
                await self._store.save(self._persona_id, sender_id, after)

    async def _announce_entry(self, announcer: SulkAnnouncer | None) -> None:
        """Announce a fresh обида entry once (best-effort, optional/scope-aware)."""
        if announcer is None:
            return
        try:
            await announcer.announce_sulk()
        except Exception:
            logger.exception("announcing sulk entry failed (ignored)")


class SulkRecoveryStep:
    """The reflect-tick обида recovery collaborator (BOB-014 .2b).

    A thin ``run()``-shaped step (matching the other reflect-tick evolvers) that decays
    each active обида by the REAL elapsed time since the last recovery tick — the
    GUARANTEED exit, since time alone brings Bob back. It stamps the clock on each run so
    the next tick decays the real gap; the first run (no prior stamp) only stamps and does
    not decay. Driven on the same slow cadence as the other reflect-tick steps. A no-op
    when Bob is not hurt, so an unwired/idle Bob behaves exactly as before.
    """

    def __init__(self, *, tracker: SulkTracker, clock: Clock) -> None:
        self._tracker = tracker
        self._clock = clock
        self._last_run_at: datetime | None = None

    async def run(self) -> None:
        """Decay each active обида by the elapsed time since the last recovery tick."""
        now = self._clock.now()
        last = self._last_run_at
        self._last_run_at = now
        if last is None:
            return
        elapsed = max(0.0, (now - last).total_seconds())
        await self._tracker.recover(elapsed_seconds=elapsed, now=now)
