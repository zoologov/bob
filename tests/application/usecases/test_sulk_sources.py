# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SulkTracker — the live обида application seam (BOB-014 .2b).

Drives the pure sulk transitions over a fake per-persona store + a fake GUPPI
announcer: entry needs a sustained critical owner-drop (never one bad message),
announce fires EXACTLY once per entry, a warm owner turn accelerates recovery while
sulking, the reflect-tick recover() is the guaranteed time-decay exit, and the store
(memory/soul) is never touched beyond the affect state. No network, all fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.social.sulk import SulkConfig, SulkState
from bob.social.usecases.sulk_sources import SulkRecoveryStep, SulkTracker

_PERSONA = "bob"
_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
_LOW_WARMTH = -0.6
_OK_WARMTH = 0.3


class _FakeSulkStore:
    """A minimal in-memory SulkStore: one SulkState per persona."""

    def __init__(self) -> None:
        self.states: dict[str, SulkState] = {}
        self.save_calls = 0

    async def load(self, persona_id: str) -> SulkState:
        return self.states.get(persona_id, SulkState())

    async def save(self, persona_id: str, state: SulkState) -> None:
        self.states[persona_id] = state
        self.save_calls += 1


class _FakeAnnouncer:
    """Counts how many times the one-shot обида announce fired."""

    def __init__(self) -> None:
        self.calls = 0

    async def announce_sulk(self) -> None:
        self.calls += 1


def _tracker(
    store: _FakeSulkStore,
    announcer: _FakeAnnouncer | None = None,
    *,
    sustain_count: int = 3,
) -> SulkTracker:
    return SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(sustain_count=sustain_count),
        announcer=announcer,
    )


async def test_current_is_not_sulking_by_default() -> None:
    tracker = _tracker(_FakeSulkStore())

    assert (await tracker.current()).active is False


async def test_one_bad_message_does_not_enter_or_announce() -> None:
    store = _FakeSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    state = await tracker.observe(
        owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=_NOW
    )

    assert state.active is False
    assert announcer.calls == 0


async def test_sustained_drop_enters_and_announces_once() -> None:
    store = _FakeSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    states = []
    for _ in range(4):  # one past the threshold to prove no double-announce
        states.append(
            await tracker.observe(
                owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=_NOW
            )
        )

    assert states[-1].active is True
    # Announce fires EXACTLY once on entry, even though we kept observing after.
    assert announcer.calls == 1


async def test_sustained_directed_hostility_enters() -> None:
    store = _FakeSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    for _ in range(3):
        state = await tracker.observe(
            owner_warmth=_OK_WARMTH, hostile=True, warmth_delta=0.0, now=_NOW
        )

    assert state.active is True
    assert announcer.calls == 1


async def test_warm_turn_accelerates_recovery_while_sulking() -> None:
    store = _FakeSulkStore()
    store.states[_PERSONA] = SulkState(
        active=True, intensity=0.8, since=_NOW, announced=True
    )
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(warmth_decay_bonus=0.5),
    )

    state = await tracker.observe(
        owner_warmth=_OK_WARMTH, hostile=False, warmth_delta=0.4, now=_NOW
    )

    # A warm owner turn pulls обида down faster than time alone.
    assert state.intensity < 0.8


async def test_recover_is_guaranteed_exit_by_time_alone() -> None:
    store = _FakeSulkStore()
    store.states[_PERSONA] = SulkState(
        active=True, intensity=1.0, since=_NOW, announced=True
    )
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(decay_per_second=0.001, exit_intensity=0.05),
    )

    state = await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)

    # Time alone (no warmth) brings Bob back — never a permanent lock-out.
    assert state.active is False


async def test_recover_is_idempotent_no_op_when_not_sulking() -> None:
    store = _FakeSulkStore()
    tracker = _tracker(store)

    await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)

    # A no-op when not hurt — never persists or reactivates обида.
    assert store.save_calls == 0
    assert (await tracker.current()).active is False


async def test_observe_with_no_announcer_is_silent_but_enters() -> None:
    store = _FakeSulkStore()
    tracker = _tracker(store, announcer=None)

    for _ in range(3):
        state = await tracker.observe(
            owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=_NOW
        )

    # обида still takes hold even with no announcer wired (best-effort, optional).
    assert state.active is True


async def test_announce_failure_never_breaks_the_entry() -> None:
    # The announce is best-effort: if GUPPI throws, обида must still take hold and be
    # persisted (the systemic notice is a nicety, not a precondition of the affect).
    class _BoomAnnouncer:
        async def announce_sulk(self) -> None:
            raise RuntimeError("guppi is down")

    store = _FakeSulkStore()
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(sustain_count=3),
        announcer=_BoomAnnouncer(),
    )

    for _ in range(3):
        state = await tracker.observe(
            owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=_NOW
        )

    assert state.active is True
    assert store.states[_PERSONA].active is True


# --- US-3 anti-Exodus: a full hurt → отход cycle touches ONLY the affect ------


async def test_full_sulk_cycle_is_anti_exodus_and_reusable() -> None:
    # US-3 / anti-Exodus: a complete обида cycle (enter → announce once → guaranteed
    # time-decay exit) is an AFFECT state only — the tracker's sole store is the
    # SulkStore (no memory/soul reset, no new Genesis), and after отход Bob is fully
    # reusable: a fresh later drop enters AND announces AFRESH (exit cleared the
    # one-shot flag), proving there is no permanent lock-out and no identity reset.
    store = _FakeSulkStore()
    announcer = _FakeAnnouncer()
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(
            sustain_count=3, decay_per_second=0.001, exit_intensity=0.05
        ),
        announcer=announcer,
    )

    # Enter обида (sustained critical drop) → announced exactly once.
    for _ in range(3):
        await tracker.observe(
            owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=_NOW
        )
    assert (await tracker.current()).active is True
    assert announcer.calls == 1

    # Guaranteed exit by time alone (no warmth offered at all).
    exited = await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)
    assert exited.active is False
    # Anti-Exodus: still a normal SulkState row (state cleared, not the persona wiped).
    assert store.states[_PERSONA].active is False
    assert store.states[_PERSONA].announced is False  # one-shot flag reset for re-entry

    # Reusable: a fresh later sustained drop enters AND announces a SECOND time.
    later = _NOW + timedelta(days=1)
    for _ in range(3):
        await tracker.observe(
            owner_warmth=_LOW_WARMTH, hostile=False, warmth_delta=0.0, now=later
        )
    assert (await tracker.current()).active is True
    assert announcer.calls == 2  # announces afresh — no stuck flag, no lock-out
    assert store.states[_PERSONA].since == later  # re-stamped to the new entry


# --- SulkRecoveryStep: the reflect-tick collaborator (real-elapsed decay) -----


class _AdvanceableClock:
    """A Clock fake whose ``now()`` can be advanced between reflect ticks."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


async def test_recovery_step_first_run_only_stamps_no_decay() -> None:
    # The first reflect tick has no prior stamp, so it cannot know an elapsed gap — it
    # only stamps the clock and must NOT decay (no spurious exit before any time passes).
    store = _FakeSulkStore()
    store.states[_PERSONA] = SulkState(
        active=True, intensity=1.0, since=_NOW, announced=True
    )
    clock = _AdvanceableClock(_NOW)
    step = SulkRecoveryStep(tracker=_tracker(store), clock=clock)

    await step.run()

    # Intensity is untouched on the very first tick (stamp-only), so Bob is not
    # accidentally recovered by a tick with no measured elapsed time.
    assert store.states[_PERSONA].intensity == 1.0


async def test_recovery_step_decays_by_real_elapsed_on_later_ticks() -> None:
    # After the first (stamp-only) tick, the next tick decays обида by the REAL elapsed
    # time between ticks — the guaranteed time-decay exit, driven on the reflect cadence.
    store = _FakeSulkStore()
    store.states[_PERSONA] = SulkState(
        active=True, intensity=1.0, since=_NOW, announced=True
    )
    clock = _AdvanceableClock(_NOW)
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(decay_per_second=0.001, exit_intensity=0.05),
    )
    step = SulkRecoveryStep(tracker=tracker, clock=clock)

    await step.run()  # stamp only
    clock.advance(seconds=10_000.0)  # a long quiet stretch
    await step.run()  # decays by the real elapsed gap

    # Enough real elapsed time has passed for the guaranteed exit (no warmth needed).
    assert store.states[_PERSONA].active is False


async def test_recovery_step_is_a_no_op_when_not_sulking() -> None:
    # An idle/never-hurt Bob: the recovery step never writes — it behaves exactly as
    # before BOB-014 (no spurious persistence on the reflect cadence).
    store = _FakeSulkStore()
    clock = _AdvanceableClock(_NOW)
    step = SulkRecoveryStep(tracker=_tracker(store), clock=clock)

    await step.run()  # stamp only
    clock.advance(seconds=10_000.0)
    await step.run()  # would decay, but there is nothing to recover

    assert store.save_calls == 0
