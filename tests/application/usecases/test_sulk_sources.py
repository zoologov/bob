# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SulkTracker — the live per-person обида seam (BOB-014 .2b, BOB-066 2.5).

Drives the pure sulk transitions over a fake per-(persona, sender) store + a fake GUPPI
announcer: entry needs a sustained critical warmth-drop (never one bad message), announce
fires EXACTLY once per entry, a warm turn accelerates recovery while sulking, the
reflect-tick recover() is the guaranteed time-decay exit, обида at one sender leaves
another untouched (addressed cooling), a group-scoped GroupSilentAnnouncer enters обида
SILENTLY, and the store (memory/soul) is never touched beyond the affect state. No
network, all fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.social.sulk import SulkConfig, SulkState
from bob.social.usecases.sulk_sources import (
    GroupSilentAnnouncer,
    SulkRecoveryStep,
    SulkTracker,
)

_PERSONA = "bob"
_OWNER = 111
_ALESHA = 222
_VLADIMIR = 333
_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
_LOW_WARMTH = -0.6
_OK_WARMTH = 0.3


class _FakePersonSulkStore:
    """A minimal in-memory PersonSulkStore: one SulkState per (persona, sender)."""

    def __init__(self) -> None:
        self.states: dict[tuple[str, int], SulkState] = {}
        self.save_calls = 0

    async def load(self, persona_id: str, sender_id: int) -> SulkState:
        return self.states.get((persona_id, sender_id), SulkState())

    async def save(self, persona_id: str, sender_id: int, state: SulkState) -> None:
        self.states[(persona_id, sender_id)] = state
        self.save_calls += 1

    async def active_sulks(self, persona_id: str) -> list[int]:
        return [
            sender
            for (persona, sender), state in self.states.items()
            if persona == persona_id and state.active
        ]


class _FakeAnnouncer:
    """Counts how many times the one-shot обида announce fired."""

    def __init__(self) -> None:
        self.calls = 0

    async def announce_sulk(self) -> None:
        self.calls += 1


def _tracker(
    store: _FakePersonSulkStore,
    announcer: _FakeAnnouncer | None = None,
    *,
    sustain_count: int = 3,
    owner_sender_id: int | None = _OWNER,
) -> SulkTracker:
    return SulkTracker(
        store=store,
        persona_id=_PERSONA,
        owner_sender_id=owner_sender_id,
        config=SulkConfig(sustain_count=sustain_count),
        announcer=announcer,
    )


async def test_current_for_is_not_sulking_by_default() -> None:
    tracker = _tracker(_FakePersonSulkStore())

    assert (await tracker.current_for(_ALESHA)).active is False


async def test_one_bad_message_does_not_enter_or_announce() -> None:
    store = _FakePersonSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    state = await tracker.observe(
        sender_id=_ALESHA,
        person_warmth=_LOW_WARMTH,
        hostile=False,
        warmth_delta=0.0,
        now=_NOW,
    )

    assert state.active is False
    assert announcer.calls == 0


async def test_sustained_drop_enters_and_announces_once() -> None:
    store = _FakePersonSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    states = []
    for _ in range(4):  # one past the threshold to prove no double-announce
        states.append(
            await tracker.observe(
                sender_id=_ALESHA,
                person_warmth=_LOW_WARMTH,
                hostile=False,
                warmth_delta=0.0,
                now=_NOW,
            )
        )

    assert states[-1].active is True
    assert announcer.calls == 1


async def test_sustained_directed_hostility_enters() -> None:
    store = _FakePersonSulkStore()
    announcer = _FakeAnnouncer()
    tracker = _tracker(store, announcer)

    for _ in range(3):
        state = await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_OK_WARMTH,
            hostile=True,
            warmth_delta=0.0,
            now=_NOW,
        )

    assert state.active is True
    assert announcer.calls == 1


async def test_sulk_at_one_sender_leaves_another_untouched() -> None:
    # 🔴 Addressed cooling: обида на Лёшу не задевает состояние по Владимиру.
    store = _FakePersonSulkStore()
    tracker = _tracker(store)

    for _ in range(3):
        await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )

    assert (await tracker.current_for(_ALESHA)).active is True
    assert (await tracker.current_for(_VLADIMIR)).active is False
    assert await tracker.active_targets() == [_ALESHA]


async def test_group_silent_announcer_enters_without_a_systemic_line() -> None:
    # Scope-aware announcer: a group entry is SILENT (the GUPPI line never fires), yet
    # обида still takes hold — the cold reads through the addressed tone.
    store = _FakePersonSulkStore()
    guppi = _FakeAnnouncer()
    tracker = _tracker(store, guppi)

    for _ in range(3):
        state = await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
            announcer=GroupSilentAnnouncer(),
        )

    assert state.active is True
    assert guppi.calls == 0  # the systemic GUPPI line stayed silent in the group


async def test_current_active_reads_the_owner_veto() -> None:
    # The proactivity veto reads the OWNER's обида, not a guest's.
    store = _FakePersonSulkStore()
    tracker = _tracker(store)

    for _ in range(3):
        await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )

    # Bob is обижен at a guest but NOT at the owner → the proactivity veto is inactive.
    assert await tracker.current_active() is False

    for _ in range(3):
        await tracker.observe(
            sender_id=_OWNER,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )

    assert await tracker.current_active() is True


async def test_warm_turn_accelerates_recovery_while_sulking() -> None:
    store = _FakePersonSulkStore()
    store.states[(_PERSONA, _ALESHA)] = SulkState(
        active=True, intensity=0.8, since=_NOW, announced=True
    )
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(warmth_decay_bonus=0.5),
    )

    state = await tracker.observe(
        sender_id=_ALESHA,
        person_warmth=_OK_WARMTH,
        hostile=False,
        warmth_delta=0.4,
        now=_NOW,
    )

    assert state.intensity < 0.8


async def test_recover_is_guaranteed_exit_by_time_alone() -> None:
    store = _FakePersonSulkStore()
    store.states[(_PERSONA, _ALESHA)] = SulkState(
        active=True, intensity=1.0, since=_NOW, announced=True
    )
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(decay_per_second=0.001, exit_intensity=0.05),
    )

    await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)

    assert (await tracker.current_for(_ALESHA)).active is False


async def test_recover_is_a_no_op_when_not_sulking() -> None:
    store = _FakePersonSulkStore()
    tracker = _tracker(store)

    await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)

    assert store.save_calls == 0
    assert (await tracker.current_for(_ALESHA)).active is False


async def test_observe_with_no_announcer_is_silent_but_enters() -> None:
    store = _FakePersonSulkStore()
    tracker = _tracker(store, announcer=None)

    for _ in range(3):
        state = await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )

    assert state.active is True


async def test_announce_failure_never_breaks_the_entry() -> None:
    class _BoomAnnouncer:
        async def announce_sulk(self) -> None:
            raise RuntimeError("guppi is down")

    store = _FakePersonSulkStore()
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(sustain_count=3),
        announcer=_BoomAnnouncer(),
    )

    for _ in range(3):
        state = await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )

    assert state.active is True
    assert store.states[(_PERSONA, _ALESHA)].active is True


# --- US-3 anti-Exodus: a full hurt → отход cycle touches ONLY the affect ------


async def test_full_sulk_cycle_is_anti_exodus_and_reusable() -> None:
    store = _FakePersonSulkStore()
    announcer = _FakeAnnouncer()
    tracker = SulkTracker(
        store=store,
        persona_id=_PERSONA,
        config=SulkConfig(
            sustain_count=3, decay_per_second=0.001, exit_intensity=0.05
        ),
        announcer=announcer,
    )

    for _ in range(3):
        await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=_NOW,
        )
    assert (await tracker.current_for(_ALESHA)).active is True
    assert announcer.calls == 1

    await tracker.recover(elapsed_seconds=10_000.0, now=_NOW)
    row = store.states[(_PERSONA, _ALESHA)]
    assert row.active is False
    assert row.announced is False  # one-shot flag reset for re-entry

    later = _NOW + timedelta(days=1)
    for _ in range(3):
        await tracker.observe(
            sender_id=_ALESHA,
            person_warmth=_LOW_WARMTH,
            hostile=False,
            warmth_delta=0.0,
            now=later,
        )
    assert (await tracker.current_for(_ALESHA)).active is True
    assert announcer.calls == 2  # announces afresh — no stuck flag, no lock-out
    assert store.states[(_PERSONA, _ALESHA)].since == later


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
    store = _FakePersonSulkStore()
    store.states[(_PERSONA, _ALESHA)] = SulkState(
        active=True, intensity=1.0, since=_NOW, announced=True
    )
    clock = _AdvanceableClock(_NOW)
    step = SulkRecoveryStep(tracker=_tracker(store), clock=clock)

    await step.run()

    assert store.states[(_PERSONA, _ALESHA)].intensity == 1.0


async def test_recovery_step_decays_by_real_elapsed_on_later_ticks() -> None:
    store = _FakePersonSulkStore()
    store.states[(_PERSONA, _ALESHA)] = SulkState(
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

    assert store.states[(_PERSONA, _ALESHA)].active is False


async def test_recovery_step_is_a_no_op_when_not_sulking() -> None:
    store = _FakePersonSulkStore()
    clock = _AdvanceableClock(_NOW)
    step = SulkRecoveryStep(tracker=_tracker(store), clock=clock)

    await step.run()  # stamp only
    clock.advance(seconds=10_000.0)
    await step.run()  # would decay, but there is nothing to recover

    assert store.save_calls == 0
