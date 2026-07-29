# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the per-person обида acceptance scenarios (BOB-066 Срез 2.5).

Binds the Gherkin steps of ``person_sulk.feature`` to the live обида seam
(:class:`SulkTracker`) over a fake per-(persona, sender) store. Drives the SAME signals
the application derives — the hostile flag comes from the real
:func:`~bob.personality.profanity.is_directed_hostility` so casual мат is honestly
distinguished from directed hostility — and asserts observable behavior through
``current_for`` / ``recover``: an обида toward one participant leaves the tone toward
another warm (addressed cooling), casual мат never enters, one bad message never enters,
and time alone always brings Bob back (INV-6, guaranteed decay exit). Living
documentation for the anti-Exodus, per-person contract of Пласт 4.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.personality.profanity import is_directed_hostility
from bob.social.sulk import SulkConfig, SulkState
from bob.social.usecases.sulk_sources import SulkTracker

scenarios("../features/person_sulk.feature")

_PERSONA = "bob"
_ALESHA = 222
_VLADIMIR = 333
_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
_COLD_WARMTH = -0.6
# A sustained run of directed-hostility turns needed to enter обида (threshold + sustain).
_SUSTAIN = 3


class _FakePersonSulkStore:
    """A minimal in-memory PersonSulkStore keyed per (persona, sender)."""

    def __init__(self) -> None:
        self.states: dict[tuple[str, int], SulkState] = {}

    async def load(self, persona_id: str, sender_id: int) -> SulkState:
        return self.states.get((persona_id, sender_id), SulkState())

    async def save(self, persona_id: str, sender_id: int, state: SulkState) -> None:
        self.states[(persona_id, sender_id)] = state

    async def active_sulks(self, persona_id: str) -> list[int]:
        return [
            sender
            for (persona, sender), state in self.states.items()
            if persona == persona_id and state.active
        ]


class _PersonSulkContext:
    """Carries the tracker + store across the BDD steps."""

    def __init__(self) -> None:
        self.store = _FakePersonSulkStore()
        self.tracker = SulkTracker(
            store=self.store,
            persona_id=_PERSONA,
            config=SulkConfig(
                sustain_count=_SUSTAIN, decay_per_second=0.001, exit_intensity=0.05
            ),
        )

    async def turn(self, sender_id: int, *, text: str, warmth: float) -> None:
        """Fold one person's turn — the hostile flag is derived exactly as the app does."""
        await self.tracker.observe(
            sender_id=sender_id,
            person_warmth=warmth,
            hostile=is_directed_hostility(text),
            warmth_delta=warmth,
            now=_NOW,
        )

    async def is_sulking_at(self, sender_id: int) -> bool:
        return (await self.tracker.current_for(sender_id)).active


@pytest.fixture
def person_sulk_context() -> _PersonSulkContext:
    return _PersonSulkContext()


@given("Боб общается с Лёшей и Владимиром")
def bob_in_group(person_sulk_context: _PersonSulkContext) -> None:
    assert person_sulk_context.store.states == {}


@when("Лёша устойчиво груб и враждебен к Бобу")
def alesha_sustained_hostile(person_sulk_context: _PersonSulkContext) -> None:
    async def _run() -> None:
        for _ in range(_SUSTAIN):
            await person_sulk_context.turn(
                _ALESHA, text="ты тупой идиот", warmth=_COLD_WARMTH
            )

    asyncio.run(_run())


@when("Лёша эмоционально матерится, но без враждебности к Бобу")
def alesha_casual_mat(person_sulk_context: _PersonSulkContext) -> None:
    async def _run() -> None:
        for _ in range(_SUSTAIN):
            await person_sulk_context.turn(
                _ALESHA, text="блин, ну охренеть как круто получилось!", warmth=0.3
            )

    asyncio.run(_run())


@when("Лёша один раз враждебен к Бобу")
def alesha_one_bad_message(person_sulk_context: _PersonSulkContext) -> None:
    asyncio.run(
        person_sulk_context.turn(_ALESHA, text="ты тупой идиот", warmth=_COLD_WARMTH)
    )


@when("проходит достаточно времени без единого тёплого слова")
def enough_time_passes(person_sulk_context: _PersonSulkContext) -> None:
    # Time ALONE (no warmth offered) drives the guaranteed decay exit.
    asyncio.run(person_sulk_context.tracker.recover(elapsed_seconds=10_000.0, now=_NOW))


@then("Боб обижен на Лёшу")
def bob_sulks_at_alesha(person_sulk_context: _PersonSulkContext) -> None:
    assert asyncio.run(person_sulk_context.is_sulking_at(_ALESHA)) is True


@then("тон Боба к Владимиру остаётся тёплым")
def tone_to_vladimir_warm(person_sulk_context: _PersonSulkContext) -> None:
    # Addressed cooling: no обида row toward Владимир, so his reply carries no cold tone.
    assert asyncio.run(person_sulk_context.is_sulking_at(_VLADIMIR)) is False


@then("Боб не обижен на Лёшу")
def bob_not_sulking_at_alesha(person_sulk_context: _PersonSulkContext) -> None:
    assert asyncio.run(person_sulk_context.is_sulking_at(_ALESHA)) is False


@then("Боб отходит и больше не обижен на Лёшу")
def bob_recovers(person_sulk_context: _PersonSulkContext) -> None:
    assert asyncio.run(person_sulk_context.is_sulking_at(_ALESHA)) is False
