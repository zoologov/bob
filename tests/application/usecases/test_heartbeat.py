# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the heartbeat ticks — InnerMonologue, mood drift, Reflect.

The ticks feed Bob's autonomous inner life (RFC §"Поток обработки": the parallel
heartbeat). Each tick is exercised once on fakes: a captured Tier 0 provider, an
in-memory state holder, and a fake repo. Periodicity (the asyncio loop) is the
runtime's job and is covered there; here we test one tick's effect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.apply_reflection import ApplyReflection, ReflectionSignal
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class CapturingProvider:
    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.calls = 0
        self.prompts: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        self.prompts.append(" ".join(m.get("content", "") for m in messages))
        return self.reply


class FakeRepo:
    def __init__(self) -> None:
        self.episodes: list[Mapping[str, object]] = []
        self.mood: Mapping[str, object] | None = None

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None:  # noqa: ARG002
        self.mood = state


class FakeSoulStore:
    """Records taste_profile writes so the reflect tick's persistence is observable."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, object]] = []

    def write_json(self, name: str, data: object) -> None:
        self.writes.append((name, data))


class StubParser:
    """A parser returning a fixed signal regardless of input."""

    def __init__(self, signal: ReflectionSignal | None) -> None:
        self._signal = signal

    def parse(
        self,
        reflection: str,  # noqa: ARG002
        *,
        topics: tuple[str, ...],  # noqa: ARG002
    ) -> ReflectionSignal | None:
        return self._signal


def _state_with_axis(axis: TasteAxis) -> PersonalityState:
    soul = SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(axes=(axis,)),
    )
    return PersonalityState(soul=soul)


def _moment() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _state(mood: Mood, baseline: Mood) -> PersonalityState:
    soul = SOUL(
        identity="Bob",
        mood=mood,
        mood_baseline=baseline,
        taste=TasteEngine(),
    )
    return PersonalityState(soul=soul)


def _router(reply: str) -> tuple[LLMRouter, CapturingProvider]:
    tier0 = CapturingProvider(reply=reply)
    router = LLMRouter(providers={0: tier0, 1: CapturingProvider(reply="unused")})
    return router, tier0


async def test_inner_monologue_runs_on_tier0() -> None:
    # Arrange
    router, tier0 = _router(reply="positive")
    state = _state(Mood(valence=0.0), Mood())
    tick = InnerMonologueTick(router=router, state=state)

    # Act
    await tick.run()

    # Assert: a private monologue was classified locally (Tier 0), not Tier 1.
    assert tier0.calls == 1


async def test_inner_monologue_prompt_carries_the_russian_directive() -> None:
    # Arrange: a self-generated thought has nothing to mirror, so the language must
    # be pinned in the prompt (BOB-012) — default Russian.
    router, tier0 = _router(reply="positive")
    state = _state(Mood(valence=0.0), Mood())
    tick = InnerMonologueTick(router=router, state=state, language="ru")

    # Act
    await tick.run()

    # Assert: the Russian directive reached the model.
    assert "по-русски" in tier0.prompts[0].casefold()


async def test_reflect_prompt_carries_the_russian_directive() -> None:
    # Arrange: the reflection tick is self-generated too — pin the language.
    router, tier0 = _router(reply="A quiet reflection.")
    state = _state(Mood(), Mood())
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=state,
        clock=FixedClock(_moment()),
        language="ru",
    )

    # Act
    await tick.run()

    # Assert
    assert "по-русски" in tier0.prompts[0].casefold()


async def test_inner_monologue_feeds_mood() -> None:
    # Arrange: a positive inner monologue should lift valence.
    router, _ = _router(reply="positive")
    state = _state(Mood(valence=0.0), Mood())
    tick = InnerMonologueTick(router=router, state=state)

    # Act
    await tick.run()

    # Assert
    assert state.soul.mood.valence > 0.0


async def test_mood_drift_pulls_toward_baseline() -> None:
    # Arrange: current mood is elevated; baseline is calm.
    state = _state(Mood(valence=0.8), Mood(valence=0.0))
    tick = MoodDriftTick(state=state)

    # Act
    await tick.run()

    # Assert: drift moves valence back toward the baseline.
    assert state.soul.mood.valence < 0.8


async def test_reflect_writes_an_episode() -> None:
    # Arrange
    router, tier0 = _router(reply="A quiet reflection on the day.")
    repo = FakeRepo()
    state = _state(Mood(), Mood())
    tick = ReflectTick(router=router, repo=repo, state=state, clock=FixedClock(_moment()))

    # Act
    await tick.run()

    # Assert: reflection ran on Tier 0 and was logged as an episode.
    assert tier0.calls == 1
    assert len(repo.episodes) == 1
    assert repo.episodes[0]["event_type"] == "reflection"


def _evolving_tick(
    *,
    reply: str,
    state: PersonalityState,
    signal: ReflectionSignal | None,
    soul_store: FakeSoulStore,
) -> tuple[ReflectTick, CapturingProvider]:
    router, tier0 = _router(reply=reply)
    apply_reflection = ApplyReflection(parser=StubParser(signal))
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=state,
        clock=FixedClock(_moment()),
        apply_reflection=apply_reflection,
        soul_store=soul_store,
    )
    return tick, tier0


async def test_reflect_evolves_soul_and_persists_on_signal() -> None:
    # Arrange: a recognised signal nudges Bob's jazz axis upward.
    state = _state_with_axis(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    soul_store = FakeSoulStore()
    tick, _ = _evolving_tick(
        reply="I love jazz lately.",
        state=state,
        signal=ReflectionSignal(topic="jazz", nudge=1.0),
        soul_store=soul_store,
    )

    # Act
    await tick.run()

    # Assert: live soul evolved AND the taste_profile was persisted.
    assert state.soul.taste.axes[0].value > 0.2
    assert state.soul.experience_count == 1
    assert any(name == "taste_profile" for name, _ in soul_store.writes)


async def test_reflect_is_a_noop_without_a_signal() -> None:
    # Arrange: parser recognises nothing.
    state = _state_with_axis(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    soul_store = FakeSoulStore()
    tick, _ = _evolving_tick(
        reply="A vague musing.",
        state=state,
        signal=None,
        soul_store=soul_store,
    )

    # Act
    await tick.run()

    # Assert: no evolution, no persistence.
    assert state.soul.taste.axes[0].value == 0.2
    assert state.soul.experience_count == 0
    assert soul_store.writes == []


async def test_reflect_double_run_is_idempotent() -> None:
    # Arrange: the same reflection text on a re-run must evolve the soul only once.
    state = _state_with_axis(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    soul_store = FakeSoulStore()
    tick, _ = _evolving_tick(
        reply="I love jazz lately.",
        state=state,
        signal=ReflectionSignal(topic="jazz", nudge=1.0),
        soul_store=soul_store,
    )

    # Act: run the identical tick twice.
    await tick.run()
    value_after_first = state.soul.taste.axes[0].value
    writes_after_first = len(soul_store.writes)
    await tick.run()

    # Assert: the second run is a no-op — soul evolved exactly once.
    assert state.soul.taste.axes[0].value == value_after_first
    assert state.soul.experience_count == 1
    assert len(soul_store.writes) == writes_after_first


async def test_reflect_without_evolution_wiring_is_log_only() -> None:
    # Arrange: no apply_reflection/soul_store injected — legacy log-only behaviour.
    router, _ = _router(reply="I love jazz lately.")
    state = _state_with_axis(TasteAxis(name="jazz", value=0.2, conviction=0.1))
    repo = FakeRepo()
    tick = ReflectTick(router=router, repo=repo, state=state, clock=FixedClock(_moment()))

    # Act
    await tick.run()

    # Assert: episode written, soul untouched.
    assert len(repo.episodes) == 1
    assert state.soul.taste.axes[0].value == 0.2
    assert state.soul.experience_count == 0
