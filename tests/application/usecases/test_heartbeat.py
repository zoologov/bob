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
from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.app import _load_soul
from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.apply_reflection import ApplyReflection, ReflectionSignal
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import (
    _MONOLOGUE_VALENCE_BAND,
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
    _bounded_valence_delta,
)
from bob.application.usecases.reappraise_reflection import ReappraisalOutcome
from bob.domain.personality.disposition import Disposition
from bob.domain.personality.mood import Mood
from bob.domain.personality.reflection import (
    LIVING_REFLECTION_EXAMPLES,
    REFLECTION_ANGLES,
    select_reflection_angle,
)
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine
from bob.infrastructure.persistence.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path


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


async def test_inner_monologue_prompt_is_conditioned_on_current_mood() -> None:
    # Arrange: a bright, high-energy mood. The monologue prompt must MIRROR it
    # (BOB-029) so the thought carries that mood instead of defaulting to gloom —
    # the old generic prompt dragged valence down every tick.
    router, tier0 = _router(reply="positive")
    mood = Mood(valence=0.8, arousal=0.6)
    state = _state(mood, Mood())
    tick = InnerMonologueTick(router=router, state=state)

    # Act
    await tick.run()

    # Assert: the live mood tone reached the model in the monologue prompt.
    assert mood.tone() in tier0.prompts[0]


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


async def test_inner_monologue_does_not_spiral_mood_to_an_extreme() -> None:
    # Arrange: baseline 0.4, and an endless run of POSITIVE private thoughts. Before
    # BOB-030 this was a positive-feedback loop that walked valence to the +1 rail.
    router, _ = _router(reply="positive")
    baseline = Mood(valence=0.4)
    state = _state(Mood(valence=0.4), baseline)
    tick = InnerMonologueTick(router=router, state=state)

    # Act: many ticks in a row, with no drift in between (worst case).
    for _ in range(30):
        await tick.run()

    # Assert: Bob's own ruminations never push valence past the homeostatic band —
    # he stays emotionally stable, not pinned at a mood ceiling.
    assert state.soul.mood.valence <= baseline.valence + _MONOLOGUE_VALENCE_BAND + 1e-9
    assert state.soul.mood.valence < 1.0


def test_bounded_valence_delta_applies_full_step_inside_the_band() -> None:
    # Well within baseline ± band: the nudge is applied in full (mood still colours).
    assert _bounded_valence_delta(current=0.4, baseline=0.4, step=0.1) == pytest.approx(0.1)
    assert _bounded_valence_delta(current=0.4, baseline=0.4, step=-0.1) == pytest.approx(-0.1)


def test_bounded_valence_delta_caps_a_push_past_the_band() -> None:
    # At the band ceiling (baseline 0.4 + band 0.4 = 0.8) an upward nudge is refused.
    assert _bounded_valence_delta(current=0.8, baseline=0.4, step=0.1) == pytest.approx(0.0)
    # Partway in, the step is clamped so it lands exactly at the ceiling, not past it.
    assert _bounded_valence_delta(current=0.75, baseline=0.4, step=0.1) == pytest.approx(0.05)


def test_bounded_valence_delta_does_not_yank_back_from_beyond_the_band() -> None:
    # Already above the band (a strong external event): a bright thought neither
    # pushes further out nor pulls back in — drift owns the return.
    assert _bounded_valence_delta(current=0.95, baseline=0.4, step=0.1) == pytest.approx(0.0)
    # ...but a darker thought from up there is still allowed to move toward baseline.
    assert _bounded_valence_delta(current=0.95, baseline=0.4, step=-0.1) == pytest.approx(-0.1)


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


async def test_reflect_evolution_survives_a_restart_via_real_soul_store(
    tmp_path: Path,
) -> None:
    # Arrange: persist through the REAL SoulStore so the change is visible "between
    # runs" (US-2). A SOUL.md + taste_profile seed make _load_soul reconstruct the
    # soul exactly as a fresh boot would after Genesis has written the artifacts.
    soul_store = SoulStore(tmp_path)
    soul_store.write_soul("# I am the Bob from the book.")
    soul_store.write_json(
        "taste_profile",
        {"axes": [{"name": "jazz", "value": 0.2, "conviction": 0.1, "experience_count": 0}]},
    )
    boot_soul = _load_soul(soul_store)
    state = PersonalityState(soul=boot_soul)
    router, _ = _router(reply="I love jazz lately.")
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=state,
        clock=FixedClock(_moment()),
        apply_reflection=ApplyReflection(
            parser=StubParser(ReflectionSignal(topic="jazz", nudge=1.0))
        ),
        soul_store=soul_store,
    )

    # Act: the reflection evolves the live soul and persists it; a "restart" reloads
    # the soul from disk exactly as the next boot would.
    await tick.run()
    reloaded = _load_soul(soul_store)

    # Assert: the evolved liking persisted and a fresh load reflects the change —
    # the round-trip the RFC promised ("изменение видно между запусками").
    assert reloaded.taste.axes[0].value > 0.2
    assert reloaded.taste.axes[0].value == state.soul.taste.axes[0].value


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


class _RecordingFascinationEvolver:
    """A FascinationEvolver double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_fascination_evolver_after_logging() -> None:
    # BOB-020 wave 2: when wired, the reflect tick drives the fascination-evolution
    # step once per tick (after the reflection episode is logged so it is available
    # as grounding). The evolver is itself idempotent; the tick just invokes it.
    router, _ = _router(reply="думал про орбиты сегодня")
    repo = FakeRepo()
    state = _state(Mood(), Mood())
    evolver = _RecordingFascinationEvolver()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=state,
        clock=FixedClock(_moment()),
        evolve_fascination=evolver,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert evolver.runs == 1  # evolver driven once


async def test_reflect_without_a_fascination_evolver_is_unaffected() -> None:
    # Backward-compatible default: no evolver wired → the tick behaves as before.
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    tick = ReflectTick(
        router=router, repo=repo, state=_state(Mood(), Mood()), clock=FixedClock(_moment())
    )

    await tick.run()

    assert len(repo.episodes) == 1


class _RecordingSulkRecoverer:
    """A SulkRecoverer double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_sulk_recoverer_after_logging() -> None:
    # BOB-014 .2b: when wired, the reflect tick drives обида recovery once per tick
    # (after the reflection episode is logged), the GUARANTEED time-decay exit.
    router, _ = _router(reply="что-то приутих сегодня")
    repo = FakeRepo()
    recoverer = _RecordingSulkRecoverer()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        recover_sulk=recoverer,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert recoverer.runs == 1  # recovery driven once


class _RecordingPhantomEvolver:
    """A PhantomEvolver double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_phantom_evolver_after_logging() -> None:
    # BOB-020 wave 3: when wired, the reflect tick drives the phantom-evolution step
    # once per tick (after the reflection episode is logged so it is available as
    # grounding). The evolver is itself slow/idempotent; the tick just invokes it.
    router, _ = _router(reply="старые маяки на рассвете")
    repo = FakeRepo()
    state = _state(Mood(), Mood())
    evolver = _RecordingPhantomEvolver()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=state,
        clock=FixedClock(_moment()),
        evolve_phantoms=evolver,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert evolver.runs == 1  # phantom evolver driven once


async def test_reflect_without_a_phantom_evolver_is_unaffected() -> None:
    # Backward-compatible default: no phantom evolver wired → the tick behaves as before.
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    tick = ReflectTick(
        router=router, repo=repo, state=_state(Mood(), Mood()), clock=FixedClock(_moment())
    )

    await tick.run()

    assert len(repo.episodes) == 1


class _RecordingConsolidator:
    """A MemoryConsolidator double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_consolidator_after_logging() -> None:
    # BOB-021: when wired, the reflect tick drives the memory-consolidation step once
    # per tick (after the reflection episode is logged). The consolidator is itself
    # rare/idempotent; the tick just invokes it on the slow cadence.
    router, _ = _router(reply="дайджест дня")
    repo = FakeRepo()
    consolidator = _RecordingConsolidator()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        consolidate_memory=consolidator,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert consolidator.runs == 1  # consolidator driven once


async def test_reflect_without_a_consolidator_is_unaffected() -> None:
    # Backward-compatible default: no consolidator wired → the tick behaves as before.
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    tick = ReflectTick(
        router=router, repo=repo, state=_state(Mood(), Mood()), clock=FixedClock(_moment())
    )

    await tick.run()

    assert len(repo.episodes) == 1


class FakeReflectionContext:
    """A read-seam double: serves recent episodes for grounding + dedup (BOB-026 .2)."""

    def __init__(self, episodes: Sequence[Mapping[str, object]]) -> None:
        self._episodes = list(episodes)
        self.calls: list[int] = []

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        self.calls.append(k)
        # Mirror the real repo: the k newest, oldest-first.
        return list(self._episodes[-k:]) if k > 0 else []


class SequencedProvider:
    """A Tier-0 provider returning each reply in turn (to model regeneration)."""

    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return reply


def _sequenced_router(replies: Sequence[str]) -> tuple[LLMRouter, SequencedProvider]:
    tier0 = SequencedProvider(replies)
    router = LLMRouter(providers={0: tier0, 1: CapturingProvider(reply="unused")})
    return router, tier0


def _reflection_episode(content: str) -> dict[str, object]:
    return {"event_type": "reflection", "content": content}


def _message_episode(content: str) -> dict[str, object]:
    return {"event_type": "message", "content": content}


async def test_reflect_grounds_the_prompt_in_recent_episodes() -> None:
    # BOB-026 .2: wired with a context seam, the reflect prompt carries fresh context
    # (recent episode content + mood tone) instead of the static generic template.
    router, tier0 = _router(reply="свежая мысль про орбиты")
    context = FakeReflectionContext([_message_episode("owner: думал про орбиты?")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert "орбиты" in tier0.prompts[0]


async def test_reflect_without_a_context_seam_uses_the_generic_prompt() -> None:
    # Backward-compatible default: no context seam wired -> the legacy static prompt.
    router, tier0 = _router(reply="тихая мысль")
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
    )

    await tick.run()

    assert "how things have been going lately" in tier0.prompts[0]


async def test_reflect_regenerates_a_near_duplicate_reflection() -> None:
    # BOB-026 .2: a fresh reflection that near-repeats a recent one triggers ONE
    # regeneration (reuse of the .1 is_bob_repeat predicate), exactly like the reply
    # guard. The retry differs and is saved.
    router, tier0 = _sequenced_router(
        ["плыву по течению этих дней", "сегодня собрал телескоп"]
    )
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 2  # one regeneration
    assert len(repo.episodes) == 1
    assert repo.episodes[0]["content"] == "сегодня собрал телескоп"


async def test_reflect_skips_when_the_regeneration_is_still_a_duplicate() -> None:
    # If even the regeneration near-repeats a recent reflection, skip the save — do
    # not add another copy to the stuck record.
    router, tier0 = _sequenced_router(["плыву по течению этих дней"])
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 2  # original + one regeneration, both duplicates
    assert repo.episodes == []  # skipped, not persisted


async def test_reflect_saves_a_novel_reflection_without_regenerating() -> None:
    # A reflection unlike any recent one is saved on the first generation (no waste).
    router, tier0 = _sequenced_router(["сегодня собрал телескоп"])
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 1  # no regeneration needed
    assert len(repo.episodes) == 1


async def test_reflect_dedup_only_compares_reflection_episodes() -> None:
    # Dedup compares against recent REFLECTION episodes only, not message turns — a
    # reflection that happens to echo a message is still saved.
    router, tier0 = _sequenced_router(["owner: привет\nbob: привет"])
    context = FakeReflectionContext([_message_episode("owner: привет\nbob: привет")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 1
    assert len(repo.episodes) == 1


async def test_reflect_skips_evolution_when_the_reflection_is_skipped() -> None:
    # When a near-duplicate reflection is skipped, the soul-evolution + downstream
    # steps must not run on a thought that was never logged.
    router, _ = _sequenced_router(["плыву по течению этих дней"])
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    consolidator = _RecordingConsolidator()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        consolidate_memory=consolidator,
    )

    await tick.run()

    assert repo.episodes == []
    assert consolidator.runs == 0  # downstream steps skipped with the reflection


# --- BOB-026 .3: grounding carries the MOOD tone + zero-window edge cases -------


async def test_reflect_grounds_the_prompt_in_the_current_mood_tone() -> None:
    # BOB-026 .2: the grounded prompt weaves the current mood's deterministic tone
    # word in (not just recent episodes) so the reflection is coloured by how Bob
    # actually feels now. An excited (high valence + arousal) mood surfaces "excited".
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([_message_episode("owner: что нового?")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(valence=0.8, arousal=0.8), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert "excited" in tier0.prompts[0]


async def test_reflect_with_only_mood_and_no_episodes_still_grounds() -> None:
    # Mood-only grounding: the seam is wired but serves NO episodes, so the prompt is
    # grounded by the mood tone alone — it must NOT fall back to the generic template.
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([])  # wired seam, but empty
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(valence=0.8, arousal=0.8), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert "excited" in tier0.prompts[0]
    assert "how things have been going lately" not in tier0.prompts[0]


async def test_reflect_with_zero_grounding_episodes_omits_episode_context() -> None:
    # grounding_episodes=0 -> _episode_contents short-circuits (no episode lines), but
    # the wired seam still supplies the mood tone, so the prompt is grounded by mood.
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([_message_episode("owner: помнишь про орбиты?")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(valence=0.8, arousal=0.8), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        grounding_episodes=0,
    )

    await tick.run()

    assert "орбиты" not in tier0.prompts[0]  # no episode lines woven in
    assert "excited" in tier0.prompts[0]  # mood still grounds it


async def test_reflect_with_zero_dedup_window_never_suppresses() -> None:
    # dedup_window=0 -> _reflection_contents short-circuits to empty, so even an exact
    # repeat of a recent reflection is NOT suppressed: it is saved on the first try.
    router, tier0 = _sequenced_router(["плыву по течению этих дней"])
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        dedup_window=0,
    )

    await tick.run()

    assert tier0.calls == 1  # no regeneration — dedup disabled
    assert len(repo.episodes) == 1  # the duplicate is kept


async def test_reflect_dedup_only_compares_within_the_window() -> None:
    # Off-by-one at the window edge: with dedup_window=1 only the SINGLE freshest
    # reflection is compared. An older identical reflection that has fallen outside
    # the window no longer suppresses a fresh thought equal to it.
    router, tier0 = _sequenced_router(["старая мысль"])
    context = FakeReflectionContext(
        [
            _reflection_episode("старая мысль"),  # outside a window of 1
            _reflection_episode("свежее наблюдение"),  # the only one compared
        ]
    )
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        dedup_window=1,
    )

    await tick.run()

    assert tier0.calls == 1  # not a duplicate of the in-window reflection
    assert len(repo.episodes) == 1


class _RecordingDeduper:
    """A FactDeduper double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_deduper_after_logging() -> None:
    # BOB-021: when wired, the reflect tick drives the fact-dedup step once per tick
    # (after the reflection episode is logged). The deduper is itself rare/idempotent;
    # the tick just invokes it on the slow cadence.
    router, _ = _router(reply="дайджест дня")
    repo = FakeRepo()
    deduper = _RecordingDeduper()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        dedup_facts=deduper,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert deduper.runs == 1  # deduper driven once


async def test_reflect_without_a_deduper_is_unaffected() -> None:
    # Backward-compatible default: no deduper wired → the tick behaves as before.
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    tick = ReflectTick(
        router=router, repo=repo, state=_state(Mood(), Mood()), clock=FixedClock(_moment())
    )

    await tick.run()

    assert len(repo.episodes) == 1


class _RecordingPatternDetectorStep:
    """A PatternDetectorStep double recording how many times the tick drove it."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


async def test_reflect_drives_the_pattern_detector_after_logging() -> None:
    # BOB-028 .2: when wired, the reflect tick drives the pattern-detection step once
    # per tick (after the reflection episode is logged so it is available as grounding).
    # The step is itself rare/idempotent; the tick just invokes it.
    router, _ = _router(reply="думал, что часто повторяюсь")
    repo = FakeRepo()
    detector = _RecordingPatternDetectorStep()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        detect_patterns=detector,
    )

    await tick.run()

    assert len(repo.episodes) == 1  # reflection still logged
    assert detector.runs == 1  # detector driven once


async def test_reflect_without_a_pattern_detector_is_unaffected() -> None:
    # Backward-compatible default: no detector wired -> the tick behaves as before.
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    tick = ReflectTick(
        router=router, repo=repo, state=_state(Mood(), Mood()), clock=FixedClock(_moment())
    )

    await tick.run()

    assert len(repo.episodes) == 1


# --- BOB-033 .2: the probabilistic reappraisal seam in ReflectTick --------------


class _FakeReappraiser:
    """A reappraiser double recording its input and returning a scripted outcome."""

    def __init__(self, outcome: ReappraisalOutcome) -> None:
        self._outcome = outcome
        self.seen: list[str] = []

    async def run(self, reflection: str) -> ReappraisalOutcome:
        self.seen.append(reflection)
        return self._outcome


async def test_reflect_stores_the_reappraised_thought_and_lifts_mood() -> None:
    # BOB-033 .2: a negative thought that the reappraiser reframes is STORED reframed,
    # and its positive step lifts mood — clamped to the BOB-030 homeostatic band.
    router, _ = _router(reply="всё впустую")
    repo = FakeRepo()
    baseline = Mood(valence=0.2)
    state = _state(Mood(valence=0.2), baseline)
    reappraiser = _FakeReappraiser(
        ReappraisalOutcome(thought="но телескоп почти готов", valence_step=0.1, reappraised=True)
    )
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=state,
        clock=FixedClock(_moment()),
        reappraise=reappraiser,
    )

    await tick.run()

    assert reappraiser.seen == ["всё впустую"]
    assert repo.episodes[0]["content"] == "но телескоп почти готов"  # reframed text stored
    assert state.soul.mood.valence > 0.2  # mood lifted by the reappraisal
    # ...but bounded: never past baseline + the BOB-030 band.
    assert state.soul.mood.valence <= baseline.valence + _MONOLOGUE_VALENCE_BAND


async def test_reflect_keeps_an_unreappraised_thought_sad_and_mood_unchanged() -> None:
    # The honest low: when the reappraiser does NOT fire (over p / not negative), the
    # thought is stored as-is and mood is untouched — lows are allowed, not forced up.
    router, _ = _router(reply="всё впустую")
    repo = FakeRepo()
    state = _state(Mood(valence=0.2), Mood(valence=0.2))
    reappraiser = _FakeReappraiser(
        ReappraisalOutcome(thought="всё впустую", valence_step=0.0, reappraised=False)
    )
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=state,
        clock=FixedClock(_moment()),
        reappraise=reappraiser,
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "всё впустую"  # stays honestly sad
    assert state.soul.mood.valence == 0.2  # mood unchanged


async def test_reflect_without_a_reappraiser_is_unaffected() -> None:
    # Backward-compatible default: no reappraiser wired -> the tick behaves as before
    # (the reflection is stored verbatim, mood untouched by reappraisal).
    router, _ = _router(reply="тихая мысль")
    repo = FakeRepo()
    state = _state(Mood(valence=0.2), Mood(valence=0.2))
    tick = ReflectTick(
        router=router, repo=repo, state=state, clock=FixedClock(_moment())
    )

    await tick.run()

    assert repo.episodes[0]["content"] == "тихая мысль"
    assert state.soul.mood.valence == 0.2


# --- BOB-047 .1: grounding excludes reflections + seeded angle variety ----------


async def test_reflect_grounding_excludes_reflection_episodes() -> None:
    # BOB-047 .1: the few-shot GROUNDING moments must come from NON-reflection episodes
    # only — a prior reflection in the recent set must NOT feed the prompt (breaking the
    # self-reinforcing register lock), while a message turn STILL grounds it.
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext(
        [
            _reflection_episode("сердце колотится в предвкушении прыжка"),
            _message_episode("owner: глянь на орбиты"),
        ]
    )
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    prompt = tier0.prompts[0]
    assert "орбиты" in prompt  # the message grounds the reflection
    assert "сердце колотится" not in prompt  # the prior reflection does NOT


async def test_reflect_dedup_still_sees_reflections_after_grounding_excludes_them() -> None:
    # BOB-047 .1: excluding reflections from GROUNDING must NOT weaken the BOB-026 dedup —
    # a fresh thought that near-repeats a recent reflection is still regenerated.
    router, tier0 = _sequenced_router(
        ["плыву по течению этих дней", "сегодня собрал телескоп"]
    )
    context = FakeReflectionContext([_reflection_episode("плыву по течению этих дней")])
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 2  # dedup still fired -> one regeneration
    assert repo.episodes[0]["content"] == "сегодня собрал телескоп"


async def test_reflect_threads_a_seeded_angle_into_the_prompt() -> None:
    # BOB-047 .1: with a seeded RNG wired, the reflect prompt carries the deterministically
    # chosen inner-thought angle — same seed -> same angle (reproducible in tests).
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([_message_episode("owner: что нового?")])
    expected = select_reflection_angle(Random(0))  # noqa: S311
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        rng=Random(0),  # noqa: S311
    )

    await tick.run()

    assert expected in tier0.prompts[0]


async def test_reflect_without_an_rng_threads_no_angle() -> None:
    # Backward-compatible default: no RNG wired -> no angle directive (legacy prompt).
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([_message_episode("owner: что нового?")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    for angle in REFLECTION_ANGLES:
        assert angle not in tier0.prompts[0]


async def test_reflect_passes_the_disposition_into_the_prompt() -> None:
    # BOB-033 .2: with a context seam wired, the reflect prompt carries the soul's
    # disposition (few-shot living palette + optimism valence-lean).
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext([_message_episode("owner: что нового?")])
    soul = SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(),
        disposition=Disposition(optimism=0.8, resilience=0.7),
    )
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=PersonalityState(soul=soul),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert "optimism" in tier0.prompts[0].casefold()  # the valence-lean reached the model


# --- BOB-047 .2: acceptance — register variety, self-feed lock, mood honesty -----


def _angle_in(prompt: str) -> str:
    """The single REFLECTION_ANGLES directive woven into ``prompt`` (exactly one)."""
    present = [angle for angle in REFLECTION_ANGLES if angle in prompt]
    assert len(present) == 1, f"expected exactly one angle, found {len(present)}"
    return present[0]


async def test_reflect_angle_varies_across_a_sequence_of_ticks() -> None:
    # THE CORE FIX: over a run of ticks on ONE shared seeded RNG, the threaded inner-
    # thought ANGLE rotates through SEVERAL distinct modes — Bob's reflections get
    # RANGE instead of locking into a single register.
    router, tier0 = _router(reply="свежая мысль про орбиты")
    context = FakeReflectionContext([_message_episode("owner: глянь на орбиты")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        rng=Random(0),  # noqa: S311
    )

    for _ in range(12):
        await tick.run()

    angles = [_angle_in(prompt) for prompt in tier0.prompts]
    assert len(angles) == 12
    assert len(set(angles)) >= 3  # several distinct registers, not one repeated


async def _run_angle_sequence(seed: int, n: int) -> list[str]:
    router, tier0 = _router(reply="свежая мысль про орбиты")
    context = FakeReflectionContext([_message_episode("owner: глянь на орбиты")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
        rng=Random(seed),  # noqa: S311
    )
    for _ in range(n):
        await tick.run()
    return [_angle_in(prompt) for prompt in tier0.prompts]


async def test_reflect_angle_sequence_is_deterministic_per_seed() -> None:
    # Determinism: two ticks wired with the SAME seed thread the SAME angle sequence —
    # reproducible in tests (the BOB-033 reappraisal-gate style).
    assert await _run_angle_sequence(7, 10) == await _run_angle_sequence(7, 10)


async def test_reflect_angle_sequences_differ_across_seeds() -> None:
    # Different seeds -> a different rotation, so the register is not globally pinned.
    assert await _run_angle_sequence(0, 10) != await _run_angle_sequence(1, 10)


async def test_reflect_grounding_excludes_every_reflection_among_many_episodes() -> None:
    # Self-feeding lock BROKEN (stronger guardrail): with several reflections AND several
    # messages interleaved, the grounding few-shot carries ONLY the message content — not
    # one reflection leaks back in to let the model mimic its own register.
    router, tier0 = _router(reply="свежая мысль")
    context = FakeReflectionContext(
        [
            _reflection_episode("сердце колотится в предвкушении"),
            _message_episode("owner: первое сообщение"),
            _reflection_episode("плыву по течению этих дней"),
            _message_episode("owner: второе сообщение"),
            _reflection_episode("пустота и тишина"),
        ]
    )
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    prompt = tier0.prompts[0]
    assert "первое сообщение" in prompt  # messages ground the reflection
    assert "второе сообщение" in prompt
    for reflection in ("сердце колотится", "плыву по течению", "пустота и тишина"):
        assert reflection not in prompt  # no reflection feeds itself back in


async def test_reflect_regenerates_a_near_verbatim_not_exact_reflection() -> None:
    # Dedup INTACT (BOB-026): a thought that is NEAR-verbatim (not byte-identical) to a
    # recent reflection — one word changed — is STILL caught by the difflib ratio and
    # regenerated, proving the dedup compares against reflections semantically, unchanged.
    router, tier0 = _sequenced_router(
        [
            "сегодня собрал телескоп и любовался орбитой",  # near-verbatim (>= 0.9)
            "поймал далёкий зов маяка",  # the novel retry
        ]
    )
    context = FakeReflectionContext(
        [_reflection_episode("сегодня собрал телескоп и любовался орбитами")]
    )
    repo = FakeRepo()
    tick = ReflectTick(
        router=router,
        repo=repo,
        state=_state(Mood(), Mood()),
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    assert tier0.calls == 2  # near-verbatim caught -> one regeneration
    assert repo.episodes[0]["content"] == "поймал далёкий зов маяка"


async def test_reflect_low_mood_with_an_angle_still_permits_a_low_prompt() -> None:
    # Mood honesty PRESERVED (BOB-033) under angle variety: a genuinely low disposition +
    # a subdued mood + a seeded angle still produces a prompt that PERMITS a low thought
    # (the honest valence-lean) — the angle nudges the KIND, it does not force positivity.
    router, tier0 = _router(reply="сегодня пусто")
    context = FakeReflectionContext([_message_episode("owner: как ты?")])
    soul = SOUL(
        identity="Bob",
        mood=Mood(valence=-0.4, arousal=0.2),
        mood_baseline=Mood(valence=-0.4),
        taste=TasteEngine(),
        disposition=Disposition(optimism=0.05, resilience=0.4),
    )
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=PersonalityState(soul=soul),
        clock=FixedClock(_moment()),
        reflection_context=context,
        rng=Random(3),  # noqa: S311
    )

    await tick.run()

    prompt = tier0.prompts[0].casefold()
    assert "honest" in prompt  # the honest valence-lean is present...
    assert "low" in prompt  # ...explicitly permitting a low thought
    _angle_in(tier0.prompts[0])  # ...and an angle is still threaded in (variety holds)


async def test_inner_monologue_negative_thought_lowers_mood() -> None:
    # Mood honesty at the monologue tick (BOB-029 regression): a genuinely NEGATIVE
    # private thought moves valence DOWN — Bob's lows are honoured, never forced up.
    router, _ = _router(reply="negative")
    baseline = Mood(valence=0.2)
    state = _state(Mood(valence=0.2), baseline)
    tick = InnerMonologueTick(router=router, state=state)

    await tick.run()

    assert state.soul.mood.valence < 0.2  # the low is honoured, not suppressed


async def test_reflect_without_rng_is_unchanged_but_keeps_the_disposition_palette() -> None:
    # Backward-compat regression: an UN-wired rng adds NO angle directive, yet the rest
    # of the .1/.2 grounded prompt is intact — the grounding moment and the default
    # disposition's few-shot palette still appear. The angle is strictly ADDITIVE, so
    # an un-upgraded (no-rng) deployment behaves exactly as before BOB-047.
    router, tier0 = _router(reply="тихая мысль")
    context = FakeReflectionContext([_message_episode("owner: глянь на орбиты")])
    tick = ReflectTick(
        router=router,
        repo=FakeRepo(),
        state=_state(Mood(), Mood()),  # default soul -> default disposition (palette on)
        clock=FixedClock(_moment()),
        reflection_context=context,
    )

    await tick.run()

    prompt = tier0.prompts[0]
    for angle in REFLECTION_ANGLES:
        assert angle not in prompt  # no angle directive without an rng
    assert "орбиты" in prompt  # grounding intact
    assert any(example in prompt for example in LIVING_REFLECTION_EXAMPLES)  # palette intact
