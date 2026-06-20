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
    with distinct, asserted text.
    """

    def __init__(self, *, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        index = min(self.calls, len(self._replies) - 1)
        self.calls += 1
        return self._replies[index]


class FakeStore:
    """In-memory ProactivityStore double, recording the saved state."""

    def __init__(self, state: ProactivityState) -> None:
        self._state = state
        self.saved: ProactivityState | None = None

    async def load(self, persona_id: str) -> ProactivityState:  # noqa: ARG002
        return self._state

    async def save(self, persona_id: str, state: ProactivityState) -> None:  # noqa: ARG002
        self.saved = state
        self._state = state


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
        clock=FixedClock(moment),
        rng=random.Random(seed),
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
