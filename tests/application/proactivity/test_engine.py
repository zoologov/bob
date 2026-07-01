# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ProactivityEngine — the drive-model → proactive message flow.

The engine turns the pure domain drive-model into an actual proactive message on
a heartbeat tick. The expensive part (the Tier-0 gate + the composed reply) must
fire ONLY when Bob actually decides to speak; the default outcome of a tick is
silence with ZERO LLM calls. These tests pin that contract on fakes (a fake
store, a fake LLM router whose providers count calls, a capturing gateway, a
fixed clock, and a seeded RNG), exercising: fire → gate → compose → post; a
governance veto → silent + zero LLM; a low urge → silent + zero LLM; a gate that
says "skip" → no message posted; and energy spent + ``last_spoke_at`` advanced
only when Bob speaks.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.application.proactivity.engine import ProactivityEngine
from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.handle_message import PersonalityState
from bob.domain.personality.conversation import RepeatThresholds
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteEngine
from bob.domain.proactivity.decision import ProactiveDecider
from bob.domain.proactivity.governance import (
    Governance,
    GovernanceConfig,
    ProactiveHistory,
)
from bob.domain.proactivity.social_energy import SocialEnergy
from bob.domain.proactivity.state import ProactivityState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

_PERSONA = "bob"
_CHAT_ID = 4242


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class CountingProvider:
    """An LLM provider that records each completion and returns scripted replies.

    Replies are scripted in order: the first ``complete`` returns the first item,
    the second the second, and so on, repeating the last item thereafter. This
    lets one Tier-0 provider serve both the gate call and the (flash) compose call
    with distinct, asserted text. Each prompt's flattened content is captured so a
    test can assert what reached the model (language directive, recalled memory).
    """

    def __init__(self, *, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.prompts: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        index = min(self.calls, len(self._replies) - 1)
        self.calls += 1
        self.prompts.append(" ".join(m.get("content", "") for m in messages))
        return self._replies[index]


class FakeRecall:
    """A MemoryRecall double returning a fixed set of recalled memories."""

    def __init__(self, memories: Sequence[str]) -> None:
        self._memories = list(memories)
        self.queries: list[str] = []

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Mapping[str, object]]:
        del k, surface_old  # this fake ignores the limit and never asks for the old blend
        self.queries.append(query)
        return [{"content": m} for m in self._memories]


class FakeEpisodeRepo:
    """An episode-save double recording every episode the engine persists."""

    def __init__(self) -> None:
        self.episodes: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)


class FakeStore:
    """In-memory ProactivityStore double, recording the saved state + timed mute."""

    def __init__(
        self, state: ProactivityState, *, mute_until: datetime | None = None
    ) -> None:
        self._state = state
        self.saved: ProactivityState | None = None
        self.mute_until = mute_until
        self.cleared_mute = False

    async def load(self, persona_id: str) -> ProactivityState:  # noqa: ARG002
        return self._state

    async def save(self, persona_id: str, state: ProactivityState) -> None:  # noqa: ARG002
        self.saved = state
        self._state = state

    async def get_mute_until(self, persona_id: str) -> datetime | None:  # noqa: ARG002
        return self.mute_until

    async def set_mute_until(
        self, persona_id: str, until: datetime | None  # noqa: ARG002
    ) -> None:
        self.mute_until = until
        if until is None:
            self.cleared_mute = True


class CapturingGateway:
    """Captures typing-indicator usage and posted replies (the ReplyGateway seam)."""

    def __init__(self) -> None:
        self.typing_opened = 0
        self.replies: list[str] = []

    def typing_indicator(self, *, chat_id: int) -> AbstractAsyncContextManager[None]:  # noqa: ARG002
        gateway = self

        class _Indicator:
            async def __aenter__(self) -> None:
                gateway.typing_opened += 1

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Indicator()

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None  # noqa: ARG002
    ) -> None:
        self.replies.append(markdown)

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None:
        # BOB-035: ReplyGateway parity; the proactive engine never posts a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> None:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

class StubReflection:
    """A reflection-salience source returning a fixed salience for the latest reflection."""

    def __init__(self, salience: float) -> None:
        self._salience = salience

    async def latest_salience(self) -> float:
        return self._salience


class StubWindow:
    """A proactive-window counter returning a fixed count for anti-spam."""

    def __init__(self, count: int) -> None:
        self._count = count

    async def proactive_count_in_window(self, *, now: datetime) -> int:  # noqa: ARG002
        return self._count


def _soul(mood: Mood) -> SOUL:
    return SOUL(identity="Bob", mood=mood, mood_baseline=Mood(), taste=TasteEngine())


def _state(
    *,
    energy: float = 1.0,
    last_spoke_at: datetime | None = None,
    last_user_msg_at: datetime | None = None,
    enabled: bool = True,
) -> ProactivityState:
    return ProactivityState(
        social_energy=SocialEnergy(energy),
        last_spoke_at=last_spoke_at,
        last_user_msg_at=last_user_msg_at,
        proactivity_enabled=enabled,
    )


def _router(gate_reply: str, compose_reply: str) -> tuple[LLMRouter, list[CountingProvider]]:
    # The gate is always Tier 0 (INNER_MONOLOGUE); a short seed composes on Tier 0
    # (flash) too — so the Tier-0 provider serves both calls in order (gate, then
    # compose). Tier 1 (plus) is wired but only used for a substantive seed.
    tier0 = CountingProvider(replies=[gate_reply, compose_reply])
    tier1 = CountingProvider(replies=[compose_reply])
    router = LLMRouter(providers={0: tier0, 1: tier1})
    return router, [tier0, tier1]


def _engine(
    *,
    store: FakeStore,
    router: LLMRouter,
    gateway: CapturingGateway,
    state_holder: PersonalityState,
    moment: datetime,
    seed: int,
    salience: float = 0.5,
    window_count: int = 0,
    governance: Governance | None = None,
    recall: FakeRecall | None = None,
    repo: FakeEpisodeRepo | None = None,
    language: str = "ru",
    fascination: object | None = None,
    sulk: object | None = None,
    repeat_thresholds: RepeatThresholds | None = None,
) -> ProactivityEngine:
    return ProactivityEngine(
        persona_id=_PERSONA,
        chat_id=_CHAT_ID,
        store=store,
        decider=ProactiveDecider(
            clock=FixedClock(moment),
            governance=governance if governance is not None else Governance(),
        ),
        router=router,
        gateway=gateway,
        personality=state_holder,
        reflection=StubReflection(salience),
        window=StubWindow(window_count),
        recall=recall if recall is not None else FakeRecall([]),
        repo=repo if repo is not None else FakeEpisodeRepo(),
        clock=FixedClock(moment),
        rng=random.Random(seed),
        language=language,
        fascination=fascination,  # type: ignore[arg-type]
        sulk=sulk,  # type: ignore[arg-type]
        repeat_thresholds=(
            repeat_thresholds if repeat_thresholds is not None else RepeatThresholds()
        ),
    )


# An open, aroused, social mood at an evening peak hour maximises the urge so the
# seeded sample fires; a low evening hour with a withdrawn mood keeps it silent.
_HIGH_MOOD = Mood(valence=0.9, arousal=0.9, openness=0.9, social=0.9)
_LOW_MOOD = Mood(valence=-0.9, arousal=-0.9, openness=-0.9, social=-0.9)


def _evening() -> datetime:
    return datetime(2026, 6, 18, 20, 0, 0, tzinfo=UTC)


def _seed_that_fires(moment: datetime, mood: Mood) -> int:
    """Find a seed whose first draw fires for a high urge (keeps the test honest)."""
    decider = ProactiveDecider(clock=FixedClock(moment), governance=Governance())
    for seed in range(1000):
        if decider.should_speak(
            mood=mood,
            silence_seconds=12.0 * 3600.0,
            salience=0.9,
            social_energy=1.0,
            history=ProactiveHistory(
                last_spoke_at=None, last_user_msg_at=None, sent_in_window=0, muted=False
            ),
            rng=random.Random(seed),
        ):
            return seed
    raise AssertionError("no firing seed found")


async def test_fire_runs_gate_compose_and_posts() -> None:
    # Arrange: a high-urge state and a seed that fires; the gate says SAY, compose replies.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="Thinking it over...\nSAY: ask how the launch went",
        compose_reply="Hey, how did the launch go today?",
    )
    gateway = CapturingGateway()
    state_holder = PersonalityState(soul=_soul(_HIGH_MOOD))
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=state_holder,
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: Bob spoke — gate + compose ran, the reply posted inside the typing indicator.
    assert spoke is True
    assert gateway.replies == ["Hey, how did the launch go today?"]
    assert gateway.typing_opened == 1
    assert sum(p.calls for p in providers) >= 2  # gate + compose


async def test_gate_and_compose_prompts_carry_the_russian_directive() -> None:
    # Arrange: a proactive message is self-generated (nothing to mirror), so both
    # the Tier-0 gate and the compose prompt must pin the language (BOB-012).
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: ask about the day", compose_reply="Как прошёл день?"
    )
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        language="ru",
    )

    # Act
    await engine.tick()

    # Assert: both the gate call and the compose call carried the Russian directive.
    tier0 = providers[0]
    assert len(tier0.prompts) >= 2
    assert "по-русски" in tier0.prompts[0].casefold()  # gate
    assert "по-русски" in tier0.prompts[1].casefold()  # compose


async def test_compose_prompt_carries_the_anti_bait_voice_and_few_shot() -> None:
    # BOB-016: reaching out unprompted is exactly where the base model wants to
    # bait for a reply + sign off with ☕, so the compose prompt must carry the
    # anti-bait voice directive AND its substance-ending few-shot exemplar.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: ask about the day", compose_reply="Как прошёл день?"
    )
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        language="ru",
    )

    await engine.tick()

    compose_prompt = providers[0].prompts[1].casefold()
    # The voice guidance (don't fish for continuation; emoji are rare) is present…
    assert "не выпрашивай продолжение" in compose_prompt
    assert "эмодзи" in compose_prompt
    # …and a substance-ending exemplar rides along (the part that breaks the tic).
    assert "это всё, что хотел знать" in compose_prompt


async def test_proactive_message_is_persisted_to_episodic_memory() -> None:
    # Arrange: a fire that composes + posts must also be saved to the episode store
    # (the same store the reactive turn uses) so Bob can reference/explain it later.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, _ = _router(
        gate_reply="SAY: a warm hello", compose_reply="Привет, как ты сегодня?"
    )
    repo = FakeEpisodeRepo()
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        repo=repo,
    )

    # Act
    await engine.tick()

    # Assert: the composed message entered the episode store.
    assert len(repo.episodes) == 1
    saved = repo.episodes[0]
    assert "Привет, как ты сегодня?" in str(saved["content"])
    assert saved["event_type"] == "proactive"


async def test_compose_is_grounded_in_recalled_real_memory() -> None:
    # Arrange: a fake recall returns a known real memory; the compose prompt must
    # carry that memory so Bob draws on something real instead of confabulating.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: follow up on the trip", compose_reply="Как поездка в горы?"
    )
    recall = FakeRecall(["Owner mentioned a hiking trip to the mountains last week"])
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=recall,
    )

    # Act
    await engine.tick()

    # Assert: recall was consulted and the real memory reached the compose prompt.
    assert recall.queries  # recall happened
    compose_prompt = providers[0].prompts[1]
    assert "hiking trip to the mountains" in compose_prompt


class _FakeFascinationReader:
    """A CurrentFascinationReader double returning a canned current passion (or none)."""

    def __init__(self, fascination: object | None) -> None:
        self._fascination = fascination

    async def current_fascination(self) -> object | None:
        return self._fascination


async def test_proactive_compose_folds_in_the_current_fascination() -> None:
    # BOB-020 wave 2: when Bob has a live fascination, its topic reaches the proactive
    # compose prompt so an unprompted reach-out can land on what he is into right now.
    from bob.domain.personality.fascination import Fascination  # noqa: PLC0415

    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    router, providers = _router(gate_reply="SAY: thinking aloud", compose_reply="привет")
    fascination = Fascination(topic="орбитальная механика", intensity=0.8, created_at=moment)
    engine = _engine(
        store=FakeStore(_state(energy=1.0)),
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        fascination=_FakeFascinationReader(fascination),
    )

    await engine.tick()

    assert "орбитальная механика" in providers[0].prompts[1]


async def test_proactive_compose_no_ops_without_a_current_fascination() -> None:
    # No live passion (reader returns None): nothing about a fascination is injected.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    router, providers = _router(gate_reply="SAY: thinking aloud", compose_reply="привет")
    engine = _engine(
        store=FakeStore(_state(energy=1.0)),
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        fascination=_FakeFascinationReader(None),
    )

    await engine.tick()

    assert "увлеч" not in providers[0].prompts[1].casefold()


async def test_skip_persists_nothing_and_does_not_recall_for_nothing() -> None:
    # Arrange: a gate that skips must not persist an episode (no message to save).
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, last_spoke_at=None))
    router, _ = _router(gate_reply="SKIP", compose_reply="unreachable")
    repo = FakeEpisodeRepo()
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        repo=repo,
    )

    # Act
    spoke = await engine.tick()

    # Assert: silent → nothing persisted to episodic memory.
    assert spoke is False
    assert repo.episodes == []


async def test_fire_spends_energy_and_advances_last_spoke() -> None:
    # Arrange
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, last_spoke_at=None))
    router, _ = _router(gate_reply="SAY: a thought", compose_reply="A thought to share.")
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    await engine.tick()

    # Assert: energy was spent and last_spoke_at advanced to now.
    assert store.saved is not None
    assert store.saved.social_energy.level < 1.0
    assert store.saved.last_spoke_at == moment


async def test_governance_veto_stays_silent_with_zero_llm_calls() -> None:
    # Arrange: muted persona (owner /quiet) — governance vetoes regardless of urge.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, enabled=False))
    router, providers = _router(gate_reply="SAY: x", compose_reply="x")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: silent, no message, and crucially ZERO LLM calls (cheap default).
    assert spoke is False
    assert gateway.replies == []
    assert sum(p.calls for p in providers) == 0


class _FakeSulkSource:
    """A SulkSource double: a fixed обида state for the proactivity veto."""

    def __init__(self, *, active: bool) -> None:
        self._active = active

    async def current_active(self) -> bool:
        return self._active


async def test_sulk_vetoes_proactivity_with_zero_llm_calls() -> None:
    # BOB-014 .2b: while обижен Bob does not write first — the sulk veto suppresses
    # proactivity exactly like /quiet, with zero LLM calls.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(gate_reply="SAY: x", compose_reply="x")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        sulk=_FakeSulkSource(active=True),
    )

    spoke = await engine.tick()

    assert spoke is False
    assert gateway.replies == []
    assert sum(p.calls for p in providers) == 0


async def test_not_sulking_does_not_veto_proactivity() -> None:
    # Not hurt → the sulk veto is off; the reach-out proceeds exactly as before.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, _providers = _router(
        gate_reply="SAY: ask how it went", compose_reply="hey, how did it go?"
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        sulk=_FakeSulkSource(active=False),
    )

    spoke = await engine.tick()

    assert spoke is True  # the veto is off → Bob speaks


async def test_low_urge_stays_silent_with_zero_llm_calls() -> None:
    # Arrange: withdrawn mood + a deep-night hour → urge is tiny; a high RNG draw misses.
    night = datetime(2026, 6, 18, 3, 0, 0, tzinfo=UTC)
    store = FakeStore(_state(energy=0.0, last_spoke_at=None))
    router, providers = _router(gate_reply="SAY: x", compose_reply="x")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_LOW_MOOD)),
        moment=night,
        seed=1,  # a draw well above the tiny fire probability
        salience=0.0,
    )

    # Act
    spoke = await engine.tick()

    # Assert: no fire, no message, ZERO LLM calls.
    assert spoke is False
    assert gateway.replies == []
    assert sum(p.calls for p in providers) == 0
    assert store.saved is None or store.saved.last_spoke_at is None


async def test_gate_skip_posts_nothing_but_runs_gate_only() -> None:
    # Arrange: Bob fires the drive, but the cheap Tier-0 gate decides to skip.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, last_spoke_at=None))
    router, providers = _router(
        gate_reply="On reflection, nothing worth interrupting for.\nSKIP",
        compose_reply="should not be composed",
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: no message posted; the gate ran (Tier 0) but compose did NOT.
    assert spoke is False
    assert gateway.replies == []
    assert providers[0].calls == 1  # gate ran once
    assert providers[1].calls == 0  # compose never ran
    # State is not mutated when Bob stays silent: energy/last_spoke unchanged.
    assert store.saved is None or store.saved.last_spoke_at is None


async def test_empty_gate_verdict_skips_with_no_message() -> None:
    # Arrange: Bob fires the drive, but the Tier-0 gate returns an empty/blank
    # verdict (no decision line at all) — the lenient parse treats that as skip.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, last_spoke_at=None))
    router, providers = _router(gate_reply="   \n\n  ", compose_reply="unreachable")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: an empty gate verdict is a skip — no post, compose never runs, and
    # the silent-tick invariant holds (state not advanced).
    assert spoke is False
    assert gateway.replies == []
    assert providers[0].calls == 1  # gate ran once
    assert providers[1].calls == 0  # compose never ran
    assert store.saved is None or store.saved.last_spoke_at is None


async def test_fire_outcome_varies_across_seeds_at_a_borderline_urge() -> None:
    # Arrange: a genuinely borderline urge (neutral mood, modest signals) so the
    # stochastic draw is the deciding factor. Across many seeds the engine must
    # both speak and stay silent — proving the firing is a real seeded sample, not
    # a deterministic gate masquerading as stochastic.
    moment = datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)  # midday, governance-clear

    async def spoke_for(seed: int) -> bool:
        store = FakeStore(_state(energy=0.5, last_spoke_at=None, last_user_msg_at=None))
        router, _ = _router(gate_reply="SAY: a small thought", compose_reply="A small thought.")
        engine = _engine(
            store=store,
            router=router,
            gateway=CapturingGateway(),
            state_holder=PersonalityState(soul=_soul(Mood())),
            moment=moment,
            seed=seed,
            salience=0.3,
        )
        return await engine.tick()

    # Act: sweep a range of seeds.
    outcomes = [await spoke_for(seed) for seed in range(60)]

    # Assert: a real stochastic sample — some ticks fire, some do not.
    assert any(outcomes), "a borderline urge should fire on at least one seed"
    assert not all(outcomes), "a borderline urge should stay silent on at least one seed"


async def test_fire_decision_is_reproducible_under_a_fixed_seed() -> None:
    # Arrange: two identically-seeded engines over identical state must reach the
    # exact same speak/silent verdict — determinism is total (clock + RNG injected).
    moment = datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)
    fixed_seed = 7

    async def spoke() -> bool:
        store = FakeStore(_state(energy=0.5, last_spoke_at=None, last_user_msg_at=None))
        router, _ = _router(gate_reply="SAY: x", compose_reply="x")
        engine = _engine(
            store=store,
            router=router,
            gateway=CapturingGateway(),
            state_holder=PersonalityState(soul=_soul(Mood())),
            moment=moment,
            seed=fixed_seed,
            salience=0.3,
        )
        return await engine.tick()

    # Act / Assert: the same seed reproduces the same decision.
    assert await spoke() == await spoke()


async def test_recovers_energy_over_silence_when_speaking() -> None:
    # Arrange: a depleted reservoir but a 2h silence since the owner last wrote.
    # The engine recovers energy over that gap before scoring the urge and, when
    # Bob speaks, the persisted reservoir reflects recovery-then-spend (not zero -
    # spend, which would have stayed pinned at the floor).
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    silence_start = moment - timedelta(hours=2)
    store = FakeStore(_state(energy=0.0, last_user_msg_at=silence_start))
    router, _ = _router(gate_reply="SAY: a thought", compose_reply="A thought.")
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        # Cooldown short enough that the 2h-old owner message does not veto.
        governance=Governance(GovernanceConfig(owner_cooldown=timedelta(minutes=1))),
    )

    # Act
    await engine.tick()

    # Assert: the persisted reservoir recovered over the 2h gap before the spend,
    # so it sits above the floor a never-recovered (0 - spend) reservoir would hold.
    assert store.saved is not None
    assert store.saved.social_energy.level > 0.0


# --- Timed-mute auto-expiry (BOB-010 Ф1 BEAD-08) ------------------------------


async def test_timed_quiet_keeps_bob_muted_before_expiry() -> None:
    # Arrange: a high-urge state that WOULD fire, but /quiet 2h is active — the
    # mute has not expired yet (now < mute_until), so governance must veto.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(
        _state(energy=1.0, enabled=False), mute_until=moment + timedelta(hours=2)
    )
    router, providers = _router(gate_reply="SAY: x", compose_reply="x")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: still muted — silent, no LLM, and the (unexpired) mute is untouched.
    assert spoke is False
    assert gateway.replies == []
    assert sum(p.calls for p in providers) == 0
    assert store.mute_until == moment + timedelta(hours=2)
    assert store.cleared_mute is False


async def test_timed_quiet_auto_unmutes_at_expiry() -> None:
    # Arrange: /quiet 2h was set in the past; now is exactly at the expiry instant,
    # so the timed mute has elapsed and Bob should be proactive again.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, enabled=False), mute_until=moment)
    router, _ = _router(
        gate_reply="SAY: how did it go", compose_reply="How did the day go?"
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: the mute expired → Bob spoke, and the expiry is cleared + the flag
    # re-enabled durably (not recomputed every tick forever).
    assert spoke is True
    assert gateway.replies == ["How did the day go?"]
    assert store.mute_until is None
    assert store.cleared_mute is True
    assert store.saved is not None
    assert store.saved.proactivity_enabled is True


async def test_timed_quiet_auto_unmutes_after_expiry() -> None:
    # Arrange: now is well past the expiry instant — the timed mute has elapsed.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(
        _state(energy=1.0, enabled=False), mute_until=moment - timedelta(hours=1)
    )
    router, _ = _router(gate_reply="SAY: a thought", compose_reply="A thought.")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: expired mute → Bob spoke again, expiry cleared, flag re-enabled.
    assert spoke is True
    assert store.mute_until is None
    assert store.cleared_mute is True


# --- Recall-aware anti-repeat on the proactive path (BOB-032 .2, R4) ----------

# A recalled episode is stored as a whole turn "<sender>: <text>\nbob: <old reply>"
# (see HandleMessage._persist); the engine recovers the "bob:" half and compares the
# fresh proactive compose against it, so Bob cannot copy his OWN recalled past reply.
_RECALLED_PAST_REPLY = "Звучит как угроза."
_RECALLED_EPISODE = f"owner: ты опять за своё\nbob: {_RECALLED_PAST_REPLY}"


def _multi_compose_router(
    *, gate_reply: str, compose_replies: Sequence[str]
) -> tuple[LLMRouter, list[CountingProvider]]:
    """A router whose Tier-0 provider serves the gate then SUCCESSIVE compose drafts.

    Scripts: ``[gate_reply, draft_1, draft_2, ...]`` on Tier 0 (a short seed composes
    on flash), so the anti-repeat retry path draws a fresh draft each regeneration.
    """
    tier0 = CountingProvider(replies=[gate_reply, *compose_replies])
    tier1 = CountingProvider(replies=list(compose_replies) or ["x"])
    router = LLMRouter(providers={0: tier0, 1: tier1})
    return router, [tier0, tier1]


async def test_proactive_repeat_of_recalled_reply_is_regenerated() -> None:
    # Arrange: the recalled memory is Bob's OWN past reply; the first compose draft
    # copies it verbatim (the bug). The guard must catch it against the recalled
    # "bob:" half, drop that exemplar, and regenerate a fresh, non-repeating draft —
    # which is what actually posts.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _multi_compose_router(
        gate_reply="SAY: follow up",
        compose_replies=[_RECALLED_PAST_REPLY, "Я тут подумал — как ты вообще?"],
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
    )

    # Act
    spoke = await engine.tick()

    # Assert: Bob spoke — but the posted message is the REGENERATED draft, never the
    # recalled-reply repeat.
    assert spoke is True
    assert gateway.replies == ["Я тут подумал — как ты вообще?"]
    assert _RECALLED_PAST_REPLY not in gateway.replies
    # Compose ran more than once (the regeneration happened).
    assert providers[0].calls >= 3  # gate + 2 compose drafts


async def test_proactive_repeat_persisted_is_the_regenerated_message() -> None:
    # The episode written to memory must be the regenerated draft, not the repeat —
    # otherwise the repeat re-enters recall and the attractor persists.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, _ = _multi_compose_router(
        gate_reply="SAY: follow up",
        compose_replies=[_RECALLED_PAST_REPLY, "Совсем другая мысль на сегодня."],
    )
    repo = FakeEpisodeRepo()
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
        repo=repo,
    )

    await engine.tick()

    assert len(repo.episodes) == 1
    assert "Совсем другая мысль на сегодня." in str(repo.episodes[0]["content"])
    assert _RECALLED_PAST_REPLY not in str(repo.episodes[0]["content"])


async def test_persistent_proactive_repeat_is_skipped_not_posted() -> None:
    # Arrange: EVERY compose draft repeats the recalled reply (a stuck attractor).
    # After the bounded regenerations the message still repeats — a proactive repeat
    # is better suppressed than sent, so the tick SKIPS posting (and persists nothing).
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, last_spoke_at=None))
    # CountingProvider repeats its last reply forever → every draft is the repeat.
    router, providers = _router(
        gate_reply="SAY: follow up", compose_reply=_RECALLED_PAST_REPLY
    )
    gateway = CapturingGateway()
    repo = FakeEpisodeRepo()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
        repo=repo,
    )

    # Act
    spoke = await engine.tick()

    # Assert: a persistent repeat is suppressed — nothing posted, nothing persisted,
    # and the silent-tick invariant holds (state not advanced).
    assert spoke is False
    assert gateway.replies == []
    assert repo.episodes == []
    assert store.saved is None or store.saved.last_spoke_at is None
    # Compose was retried up to the bound (gate + initial + retries), then gave up.
    assert providers[0].calls >= 2


async def test_non_repeating_proactive_message_posts_normally() -> None:
    # A composed message that does NOT repeat any recalled reply posts on the first
    # draft — the guard never false-fires on a genuinely fresh message.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: follow up", compose_reply="Как ты сегодня? Я тут вспомнил тебя."
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
    )

    # Act
    spoke = await engine.tick()

    # Assert: posted on the first draft — no needless regeneration.
    assert spoke is True
    assert gateway.replies == ["Как ты сегодня? Я тут вспомнил тебя."]
    assert providers[0].calls == 2  # gate + ONE compose (no retry)


async def test_anti_repeat_retry_still_grounds_in_real_recalled_memory() -> None:
    # The anti-repeat retry must NOT break grounding: the regenerated compose still
    # carries the FACT content of the recalled memory (only the copied reply exemplar
    # is withheld). Here the recall is a FACT-only memory (no "bob:" half) plus the
    # copyable reply episode; the fact must survive into the retry's prompt.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _multi_compose_router(
        gate_reply="SAY: follow up",
        compose_replies=[_RECALLED_PAST_REPLY, "Расскажи, как поход?"],
    )
    fact = "owner went hiking in the mountains last week"
    engine = _engine(
        store=store,
        router=router,
        gateway=CapturingGateway(),
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([fact, _RECALLED_EPISODE]),
    )

    await engine.tick()

    # The retry compose (3rd Tier-0 prompt) still carries the FACT memory…
    retry_prompt = providers[0].prompts[2]
    assert "hiking in the mountains" in retry_prompt
    # …but no longer carries the copied reply exemplar (attractor broken).
    assert _RECALLED_PAST_REPLY not in retry_prompt


async def test_proactive_posts_last_draft_that_clears_after_full_bound() -> None:
    # Boundary (R4): the draft repeats through BOTH regenerations, then the final
    # (third) draft clears the bar — the engine posts that last fresh draft rather than
    # skipping. Covers the "exhausted the bound but last draft is clean" branch: it must
    # NOT be confused with the give-up-and-skip path.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _multi_compose_router(
        gate_reply="SAY: follow up",
        compose_replies=[
            _RECALLED_PAST_REPLY,  # initial draft: repeat
            _RECALLED_PAST_REPLY,  # retry 1: still a repeat
            "Наконец-то совершенно свежая реплика.",  # retry 2: clears the bar
        ],
    )
    gateway = CapturingGateway()
    repo = FakeEpisodeRepo()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
        repo=repo,
    )

    spoke = await engine.tick()

    # The last draft cleared the bar after the full bound — it posts (not skipped).
    assert spoke is True
    assert gateway.replies == ["Наконец-то совершенно свежая реплика."]
    assert _RECALLED_PAST_REPLY not in str(repo.episodes[0]["content"])
    assert providers[0].calls == 4  # gate + initial + 2 retries


async def test_proactive_same_topic_different_wording_is_not_regenerated() -> None:
    # No false positive (R4): the fresh draft is on the SAME topic as the recalled
    # reply (an echoed keyword) but substantively different wording — it must NOT be
    # mistaken for a repeat and post on the first draft (guard against over-firing).
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: follow up",
        compose_reply="Разве это угроза? Я передумал — давай поговорим по-другому.",
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([_RECALLED_EPISODE]),
    )

    spoke = await engine.tick()

    assert spoke is True
    assert gateway.replies == ["Разве это угроза? Я передумал — давай поговорим по-другому."]
    assert providers[0].calls == 2  # gate + ONE compose — no needless regeneration


async def test_proactive_with_no_recall_posts_without_guard_firing() -> None:
    # Regression / boundary: with NO recalled memories the recall-aware guard has no
    # exemplars to compare against — the normal proactive path is unaffected and posts
    # on the first draft.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0))
    router, providers = _router(
        gate_reply="SAY: follow up", compose_reply="Просто хотел сказать привет."
    )
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
        recall=FakeRecall([]),
    )

    spoke = await engine.tick()

    assert spoke is True
    assert gateway.replies == ["Просто хотел сказать привет."]
    assert providers[0].calls == 2  # gate + ONE compose


async def test_permanent_quiet_stays_muted_without_expiry() -> None:
    # Arrange: a permanent /quiet (proactivity off, NO mute_until) — Bob must stay
    # muted indefinitely (only /wake un-mutes him), never auto-re-enabled.
    moment = _evening()
    seed = _seed_that_fires(moment, _HIGH_MOOD)
    store = FakeStore(_state(energy=1.0, enabled=False), mute_until=None)
    router, providers = _router(gate_reply="SAY: x", compose_reply="x")
    gateway = CapturingGateway()
    engine = _engine(
        store=store,
        router=router,
        gateway=gateway,
        state_holder=PersonalityState(soul=_soul(_HIGH_MOOD)),
        moment=moment,
        seed=seed,
        salience=0.9,
    )

    # Act
    spoke = await engine.tick()

    # Assert: still muted — silent, zero LLM, no auto re-enable, no state write.
    assert spoke is False
    assert gateway.replies == []
    assert sum(p.calls for p in providers) == 0
    assert store.cleared_mute is False
    assert store.saved is None or store.saved.proactivity_enabled is False
