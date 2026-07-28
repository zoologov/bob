# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the fascination source adapters (BOB-020 wave 2).

Two application adapters: :class:`RepoFascinationGrounding` (Bob's real grounding
material — his latest reflection + the topics he holds strong opinions on, read off
the live personality state) and :class:`StoreFascinationReader` (loads the persisted
fascination, ages it against the clock, and drops a faded one — the read seam the
reply/proactive compose surfaces). Covered on fakes, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.application.usecases.handle_message import PersonalityState
from bob.personality.fascination import Fascination
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine
from bob.personality.usecases.fascination_sources import (
    RepoFascinationGrounding,
    StoreFascinationReader,
)

_PERSONA = "bob"
_T0 = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeReflectionReader:
    def __init__(self, text: str | None) -> None:
        self._text = text

    async def latest_reflection_text(self) -> str | None:
        return self._text


class FakeStore:
    def __init__(self, current: Fascination | None) -> None:
        self.current = current

    async def load(self, persona_id: str) -> Fascination | None:  # noqa: ARG002
        return self.current

    async def save(self, persona_id: str, fascination: Fascination) -> None:  # noqa: ARG002
        self.current = fascination


def _soul(axes: tuple[TasteAxis, ...]) -> SOUL:
    neutral = Mood()
    return SOUL(
        identity="Bob",
        mood=neutral,
        mood_baseline=neutral,
        taste=TasteEngine(axes=axes),
    )


class TestGrounding:
    async def test_returns_latest_reflection_text(self) -> None:
        grounding = RepoFascinationGrounding(
            reflection=FakeReflectionReader("думал про орбиты"),
            personality=PersonalityState(soul=_soul(())),
        )

        assert await grounding.latest_reflection_text() == "думал про орбиты"

    def test_strong_taste_topics_are_the_high_conviction_axes(self) -> None:
        axes = (
            TasteAxis(name="космос", value=0.9, conviction=0.8),
            TasteAxis(name="мелочь", value=0.1, conviction=0.1),  # weak — excluded
            TasteAxis(name="музыка", value=-0.8, conviction=0.7),
        )
        grounding = RepoFascinationGrounding(
            reflection=FakeReflectionReader(None),
            personality=PersonalityState(soul=_soul(axes)),
        )

        topics = grounding.strong_taste_topics()

        assert "космос" in topics
        assert "музыка" in topics
        assert "мелочь" not in topics

    def test_strong_taste_topics_are_strongest_first(self) -> None:
        axes = (
            TasteAxis(name="слабее", value=0.5, conviction=0.6),
            TasteAxis(name="сильнее", value=0.95, conviction=0.9),
        )
        grounding = RepoFascinationGrounding(
            reflection=FakeReflectionReader(None),
            personality=PersonalityState(soul=_soul(axes)),
        )

        topics = grounding.strong_taste_topics()

        assert topics[0] == "сильнее"

    def test_no_axes_yields_no_topics(self) -> None:
        grounding = RepoFascinationGrounding(
            reflection=FakeReflectionReader(None),
            personality=PersonalityState(soul=_soul(())),
        )

        assert grounding.strong_taste_topics() == ()


class TestReader:
    async def test_returns_a_fresh_non_faded_fascination_aged(self) -> None:
        fresh = Fascination(topic="орбиты", intensity=0.9, created_at=_T0)
        reader = StoreFascinationReader(
            persona_id=_PERSONA,
            store=FakeStore(fresh),
            clock=FakeClock(_T0 + timedelta(hours=1)),
        )

        result = await reader.current_fascination()

        assert result is not None
        assert result.topic == "орбиты"
        # Aged: intensity has decayed a touch from the stored value.
        assert result.intensity <= 0.9

    async def test_returns_none_when_store_empty(self) -> None:
        reader = StoreFascinationReader(
            persona_id=_PERSONA, store=FakeStore(None), clock=FakeClock(_T0)
        )

        assert await reader.current_fascination() is None

    async def test_drops_a_faded_fascination(self) -> None:
        old = Fascination(topic="старое", intensity=1.0, created_at=_T0)
        reader = StoreFascinationReader(
            persona_id=_PERSONA,
            store=FakeStore(old),
            clock=FakeClock(_T0 + timedelta(hours=10_000)),
        )

        assert await reader.current_fascination() is None
