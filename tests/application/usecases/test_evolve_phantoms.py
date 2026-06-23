# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for EvolvePhantoms — the rare, grounded phantom-evolution step (BOB-020).

On the reflect tick Bob's phantom preferences come alive: a fresh symphony emerges
from his REAL inner life (a strong taste topic / recent reflection — never random),
an old one fades, the set stays bounded. Covered here on fakes (no network): grounded
emergence persists + updates the live soul, idempotency (a double tick is one
effect, no churn), a no-op without grounding material, and the slowness gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from bob.application.usecases.evolve_phantoms import EvolvePhantoms
from bob.application.usecases.handle_message import PersonalityState
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteEngine


def _soul(phantoms: tuple[str, ...]) -> SOUL:
    return SOUL(
        identity="I am Bob.",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(),
        phantom_prefs=phantoms,
    )


@dataclass
class FakeWriter:
    """In-memory PhantomProfileWriter double recording what was persisted."""

    saved: object = None
    writes: int = 0

    def write_json(self, name: str, data: object) -> None:
        assert name == "phantom_prefs"
        self.saved = data
        self.writes += 1


class FakeGrounding:
    def __init__(self, *, reflection: str | None, taste_topics: tuple[str, ...]) -> None:
        self._reflection = reflection
        self._taste_topics = taste_topics

    async def latest_reflection_text(self) -> str | None:
        return self._reflection

    def strong_taste_topics(self) -> tuple[str, ...]:
        return self._taste_topics


def _always() -> Random:
    class _Stub(Random):
        def random(self) -> float:
            return 0.0

    return _Stub()


def _never() -> Random:
    class _Stub(Random):
        def random(self) -> float:
            return 0.999999

    return _Stub()


async def test_emergence_persists_and_updates_live_soul() -> None:
    # Arrange: a strong taste topic Bob isn't yet phantom-attached to.
    state = PersonalityState(soul=_soul(("кофе", "дождь")))
    writer = FakeWriter()
    step = EvolvePhantoms(
        state=state,
        writer=writer,
        grounding=FakeGrounding(reflection=None, taste_topics=("ночные поезда",)),
        rng=_always(),
        max_count=5,
    )

    # Act
    await step.run()

    # Assert: the grounded phantom joined the live soul and was persisted.
    assert "ночные поезда" in state.soul.phantom_prefs
    assert writer.writes == 1
    assert writer.saved == {"preferences": ["кофе", "дождь", "ночные поезда"]}


async def test_no_grounding_material_is_a_noop() -> None:
    # Arrange: no reflection, no strong tastes → nothing to ground a change.
    soul = _soul(("кофе",))
    state = PersonalityState(soul=soul)
    writer = FakeWriter()
    step = EvolvePhantoms(
        state=state,
        writer=writer,
        grounding=FakeGrounding(reflection=None, taste_topics=()),
        rng=_always(),
    )

    # Act
    await step.run()

    # Assert: Bob invents nothing; no persistence, live soul untouched.
    assert state.soul is soul
    assert writer.writes == 0


async def test_idempotent_double_tick_is_one_effect() -> None:
    # Arrange
    state = PersonalityState(soul=_soul(("кофе",)))
    writer = FakeWriter()
    step = EvolvePhantoms(
        state=state,
        writer=writer,
        grounding=FakeGrounding(reflection=None, taste_topics=("ночные поезда",)),
        rng=_always(),
    )

    # Act: two ticks in the same period (the candidate is already grounded).
    await step.run()
    after_first = state.soul.phantom_prefs
    await step.run()

    # Assert: the second tick adds nothing — no churn, one persisted effect.
    assert "ночные поезда" in after_first
    assert state.soul.phantom_prefs == after_first
    assert writer.writes == 1


async def test_slowness_gate_closed_is_a_noop() -> None:
    # Arrange: grounding exists, but this step's slowness gate stays shut.
    soul = _soul(("кофе",))
    state = PersonalityState(soul=soul)
    writer = FakeWriter()
    step = EvolvePhantoms(
        state=state,
        writer=writer,
        grounding=FakeGrounding(reflection=None, taste_topics=("ночные поезда",)),
        rng=_never(),
    )

    # Act
    await step.run()

    # Assert: most steps leave the set untouched (slow).
    assert state.soul is soul
    assert writer.writes == 0


async def test_emergence_bumps_experience_count() -> None:
    # Arrange
    state = PersonalityState(soul=_soul(("кофе",)))
    before = state.soul.experience_count
    step = EvolvePhantoms(
        state=state,
        writer=FakeWriter(),
        grounding=FakeGrounding(reflection=None, taste_topics=("ночные поезда",)),
        rng=_always(),
    )

    # Act
    await step.run()

    # Assert: a phantom shift is a self-evolution step.
    assert state.soul.experience_count == before + 1


async def test_reflection_grounds_the_candidate_when_no_strong_tastes() -> None:
    # Arrange: no strong tastes, but a fresh reflection supplies grounding.
    state = PersonalityState(soul=_soul(("кофе",)))
    step = EvolvePhantoms(
        state=state,
        writer=FakeWriter(),
        grounding=FakeGrounding(reflection="старые маяки", taste_topics=()),
        rng=_always(),
    )

    # Act
    await step.run()

    # Assert: the reflection-derived phantom emerged (grounded, not invented).
    assert "старые маяки" in state.soul.phantom_prefs


async def test_deterministic_under_seed() -> None:
    # Arrange: identical seeds reproduce the same outcome.
    grounding = FakeGrounding(reflection=None, taste_topics=("ночные поезда",))

    def _build() -> tuple[PersonalityState, EvolvePhantoms]:
        state = PersonalityState(soul=_soul(("кофе",)))
        step = EvolvePhantoms(
            state=state, writer=FakeWriter(), grounding=grounding, rng=Random(11)
        )
        return state, step

    state_a, step_a = _build()
    state_b, step_b = _build()
    await step_a.run()
    await step_b.run()

    # Assert
    assert state_a.soul.phantom_prefs == state_b.soul.phantom_prefs
