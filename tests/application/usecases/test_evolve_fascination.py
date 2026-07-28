# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for EvolveFascination — the rare, grounded fascination-evolution step (BOB-020).

On the reflect tick Bob's current fascination evolves: derived/refreshed (grounded
in his recent reflections and strong tastes — never random) by a cheap Tier-0 pick,
decaying with age, replaced only once it has faded past the floor. Covered here on
fakes (no network): grounded derivation, idempotency (a double tick is one shift),
decay-floor replacement, the heuristic fallback when Tier 0 yields nothing, and a
no-op when there is no grounding material at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.personality.fascination import Fascination
from bob.personality.usecases.evolve_fascination import (
    EvolveFascination,
    FascinationGrounding,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRequest

_PERSONA = "bob"
_T0 = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeStore:
    """In-memory FascinationStore double."""

    def __init__(self, initial: Fascination | None = None) -> None:
        self.current = initial
        self.saves = 0

    async def load(self, persona_id: str) -> Fascination | None:  # noqa: ARG002
        return self.current

    async def save(self, persona_id: str, fascination: Fascination) -> None:  # noqa: ARG002
        self.current = fascination
        self.saves += 1


class FakeRouter:
    """Records requests and replies with a scripted topic line."""

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.requests: list[LLMRequest] = []

    async def run(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self.reply


class FakeGrounding:
    def __init__(self, *, reflection: str | None, taste_topics: tuple[str, ...]) -> None:
        self._reflection = reflection
        self._taste_topics = taste_topics

    async def latest_reflection_text(self) -> str | None:
        return self._reflection

    def strong_taste_topics(self) -> tuple[str, ...]:
        return self._taste_topics


def _evolve(
    *,
    store: FakeStore,
    router: FakeRouter,
    grounding: FakeGrounding,
    clock: FakeClock,
    initial_intensity: float = 0.85,
) -> EvolveFascination:
    return EvolveFascination(
        persona_id=_PERSONA,
        store=store,
        router=router,
        grounding=grounding,
        clock=clock,
        initial_intensity=initial_intensity,
    )


class TestGroundedDerivation:
    async def test_derives_fascination_from_tier0_pick(self) -> None:
        store = FakeStore(initial=None)
        router = FakeRouter(reply="орбитальная механика")
        grounding = FakeGrounding(
            reflection="думал об орбитах", taste_topics=("звёзды",)  # noqa: RUF001
        )
        clock = FakeClock(_T0)

        await _evolve(store=store, router=router, grounding=grounding, clock=clock).run()

        assert store.current is not None
        assert store.current.topic == "орбитальная механика"
        assert store.current.created_at == _T0

    async def test_grounding_material_is_handed_to_the_model(self) -> None:
        router = FakeRouter(reply="x")
        grounding = FakeGrounding(
            reflection="я размышлял о памяти", taste_topics=("музыка",)  # noqa: RUF001
        )

        await _evolve(
            store=FakeStore(),
            router=router,
            grounding=grounding,
            clock=FakeClock(_T0),
        ).run()

        sent = " ".join(
            str(m.get("content", "")) for r in router.requests for m in r.messages
        )
        if router.requests and router.requests[0].shareable_context:
            sent += " " + str(router.requests[0].shareable_context)
        assert "память" in sent or "музыка" in sent

    async def test_intensity_starts_high_on_a_fresh_pick(self) -> None:
        store = FakeStore(initial=None)

        await _evolve(
            store=store,
            router=FakeRouter(reply="фуги"),
            grounding=FakeGrounding(reflection="r", taste_topics=()),
            clock=FakeClock(_T0),
            initial_intensity=0.9,
        ).run()

        assert store.current is not None
        assert store.current.intensity == pytest.approx(0.9)


class TestIdempotency:
    async def test_double_tick_is_a_single_shift(self) -> None:
        store = FakeStore(initial=None)
        clock = FakeClock(_T0)
        evolve = _evolve(
            store=store,
            router=FakeRouter(reply="тема А"),  # noqa: RUF001
            grounding=FakeGrounding(reflection="r", taste_topics=()),
            clock=clock,
        )

        await evolve.run()
        first = store.current
        await evolve.run()  # same period — fresh fascination has not faded

        assert store.current == first
        assert store.saves == 1

    async def test_a_strong_current_fascination_is_not_replaced(self) -> None:
        strong = Fascination(topic="существующее", intensity=0.8, created_at=_T0)
        store = FakeStore(initial=strong)
        router = FakeRouter(reply="нечто иное")

        # Only a little time passes: still well above the decay floor.
        await _evolve(
            store=store,
            router=router,
            grounding=FakeGrounding(reflection="r", taste_topics=()),
            clock=FakeClock(_T0 + timedelta(hours=1)),
        ).run()

        assert store.current is not None
        assert store.current.topic == "существующее"
        assert router.requests == []  # no Tier-0 call when nothing to shift


class TestDecayFloorReplacement:
    async def test_replaced_only_after_decay_below_floor(self) -> None:
        old = Fascination(topic="старое", intensity=1.0, created_at=_T0)
        store = FakeStore(initial=old)
        router = FakeRouter(reply="свежее")

        # Far in the future: the old passion has decayed past the floor.
        await _evolve(
            store=store,
            router=router,
            grounding=FakeGrounding(reflection="новая мысль", taste_topics=()),
            clock=FakeClock(_T0 + timedelta(hours=10_000)),
        ).run()

        assert store.current is not None
        assert store.current.topic == "свежее"
        assert store.current.created_at == _T0 + timedelta(hours=10_000)


class TestHeuristicFallback:
    async def test_falls_back_to_grounding_when_tier0_blank(self) -> None:
        store = FakeStore(initial=None)
        router = FakeRouter(reply="   ")  # Tier 0 gave nothing usable
        grounding = FakeGrounding(reflection="увлёкся фракталами", taste_topics=("математика",))

        await _evolve(store=store, router=router, grounding=grounding, clock=FakeClock(_T0)).run()

        assert store.current is not None
        # The fallback is grounded too — a real taste topic or reflection seed.
        assert store.current.topic

    async def test_no_op_when_no_grounding_material_at_all(self) -> None:
        store = FakeStore(initial=None)
        router = FakeRouter(reply="")
        grounding = FakeGrounding(reflection=None, taste_topics=())

        await _evolve(store=store, router=router, grounding=grounding, clock=FakeClock(_T0)).run()

        assert store.current is None
        assert store.saves == 0

    async def test_no_op_when_grounding_yields_only_a_blank_topic(self) -> None:
        # Edge: a degenerate strong-taste source surfaces an EMPTY topic (no reflection,
        # Tier 0 also blank). The heuristic fallback yields that empty topic, so the
        # step must no-op rather than persist a blank fascination (no fabrication).
        store = FakeStore(initial=None)
        router = FakeRouter(reply="")  # Tier 0 gave nothing
        grounding = FakeGrounding(reflection=None, taste_topics=("",))

        await _evolve(store=store, router=router, grounding=grounding, clock=FakeClock(_T0)).run()

        assert store.current is None
        assert store.saves == 0


def test_grounding_protocol_is_structural() -> None:
    # FakeGrounding satisfies the FascinationGrounding protocol structurally.
    grounding: FascinationGrounding = FakeGrounding(reflection=None, taste_topics=())
    assert grounding is not None
