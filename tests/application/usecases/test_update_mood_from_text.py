# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for UpdateMoodFromText — Tier 0 sentiment + signals → updated Mood.

A fake provider stands in for the local Tier 0 model (no network), and a fixed
Clock makes time-of-day deterministic. The use-case orchestrates; the Mood math
itself lives in the pure domain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.usecases.update_mood_from_text import (
    TextSignals,
    UpdateMoodFromText,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class FixedClock:
    """A Clock that always returns a configured timezone-aware instant."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class StubProvider:
    """Fake Tier 0 LLMProvider returning a canned sentiment label."""

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        return self.reply


def _usecase(*, sentiment: str, moment: datetime) -> tuple[UpdateMoodFromText, StubProvider]:
    provider = StubProvider(reply=sentiment)
    router = LLMRouter(providers={0: provider, 1: StubProvider(reply="unused")})
    usecase = UpdateMoodFromText(router=router, clock=FixedClock(moment))
    return usecase, provider


def _daytime() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _late_night() -> datetime:
    return datetime(2026, 6, 18, 3, 0, 0, tzinfo=UTC)


async def test_positive_sentiment_raises_valence() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="positive", moment=_daytime())
    mood = Mood(valence=0.0)
    signals = TextSignals(text="this is wonderful, thank you!", message_count=1, present=True)

    # Act
    updated = await usecase.run(mood, signals)

    # Assert: positive sentiment nudges valence up.
    assert updated.valence > mood.valence


async def test_negative_sentiment_lowers_valence() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="negative", moment=_daytime())
    mood = Mood(valence=0.0)
    signals = TextSignals(text="this is awful and I'm angry", message_count=1, present=True)

    # Act
    updated = await usecase.run(mood, signals)

    # Assert
    assert updated.valence < mood.valence


async def test_neutral_sentiment_leaves_valence_unchanged() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="neutral", moment=_daytime())
    mood = Mood(valence=0.2)
    signals = TextSignals(text="the meeting is at noon", message_count=1, present=True)

    # Act
    updated = await usecase.run(mood, signals)

    # Assert: neutral text does not move valence.
    assert updated.valence == pytest.approx(mood.valence)


async def test_sentiment_runs_on_tier0_provider() -> None:
    # Arrange
    usecase, provider = _usecase(sentiment="positive", moment=_daytime())
    signals = TextSignals(text="hi", message_count=1, present=True)

    # Act
    await usecase.run(Mood(), signals)

    # Assert: the local Tier 0 provider performed the sentiment classification.
    assert len(provider.calls) == 1


async def test_high_message_frequency_raises_arousal() -> None:
    # Arrange: a burst of messages is stimulating.
    usecase, _ = _usecase(sentiment="neutral", moment=_daytime())
    mood = Mood(arousal=0.0)
    busy = TextSignals(text="hey", message_count=10, present=True)

    # Act
    updated = await usecase.run(mood, busy)

    # Assert
    assert updated.arousal > mood.arousal


async def test_late_night_lowers_arousal() -> None:
    # Arrange: same single message, but at 3am.
    usecase, _ = _usecase(sentiment="neutral", moment=_late_night())
    mood = Mood(arousal=0.0)
    signals = TextSignals(text="still up?", message_count=1, present=True)

    # Act
    updated = await usecase.run(mood, signals)

    # Assert: the late hour pulls arousal down (winding down).
    assert updated.arousal < mood.arousal


async def test_user_presence_raises_social() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="neutral", moment=_daytime())
    mood = Mood(social=0.0)
    present = TextSignals(text="hello", message_count=1, present=True)

    # Act
    updated = await usecase.run(mood, present)

    # Assert: an engaged user lifts the social axis.
    assert updated.social > mood.social


async def test_user_absence_lowers_social() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="neutral", moment=_daytime())
    mood = Mood(social=0.3)
    absent = TextSignals(text="(no one around)", message_count=0, present=False)

    # Act
    updated = await usecase.run(mood, absent)

    # Assert
    assert updated.social < mood.social


async def test_result_stays_within_mood_bounds() -> None:
    # Arrange: already-saturated mood + a strong positive signal.
    usecase, _ = _usecase(sentiment="positive", moment=_daytime())
    mood = Mood(valence=1.0, social=1.0)
    signals = TextSignals(text="best day ever!!!", message_count=10, present=True)

    # Act
    updated = await usecase.run(mood, signals)

    # Assert: clamping keeps every axis within [-1, 1].
    assert updated.valence <= 1.0
    assert updated.social <= 1.0


async def test_run_is_deterministic_for_fixed_inputs() -> None:
    # Arrange
    usecase, _ = _usecase(sentiment="positive", moment=_daytime())
    mood = Mood(valence=0.1)
    signals = TextSignals(text="nice", message_count=2, present=True)

    # Act
    first = await usecase.run(mood, signals)
    second = await usecase.run(mood, signals)

    # Assert: same inputs (fixed clock + stub sentiment) → same mood.
    assert first == second


# --- BOB-033 .3: social co-regulation (asymmetric contagion + low-displacement) ---


def _disposed(
    *, sentiment: str, moment: datetime, disposition: Disposition
) -> UpdateMoodFromText:
    provider = StubProvider(reply=sentiment)
    router = LLMRouter(providers={0: provider, 1: StubProvider(reply="unused")})
    return UpdateMoodFromText(
        router=router, clock=FixedClock(moment), disposition=disposition
    )


async def test_positive_lifts_valence_more_than_negative_dips_it() -> None:
    # The structural anti-depressant (BOB-033 .3): a warm message moves Bob's valence
    # UP more than an equally-strong cold one drags it down — disposition asymmetry.
    disp = Disposition(optimism=0.8, resilience=0.7)
    warm = _disposed(sentiment="positive", moment=_daytime(), disposition=disp)
    cold = _disposed(sentiment="negative", moment=_daytime(), disposition=disp)
    signals = TextSignals(text="...", message_count=1, present=True)

    lifted = await warm.run(Mood(valence=0.0), signals)
    dipped = await cold.run(Mood(valence=0.0), signals)

    lift = lifted.valence - 0.0
    dip = 0.0 - dipped.valence
    assert lift > dip > 0.0


async def test_warm_message_pulls_mood_toward_disposition_baseline() -> None:
    # "Displace the low": from a dip, a warm exchange charges Bob back up — it tugs
    # mood TOWARD the warmer baseline (lift_toward fired), not just adds a flat delta.
    disp = Disposition(optimism=0.8, resilience=0.7)
    warm = _disposed(sentiment="positive", moment=_daytime(), disposition=disp)
    low = Mood(valence=-0.6, social=-0.5)
    target = Mood(valence=0.4, social=0.55)
    signals = TextSignals(text="hey, missed you!", message_count=1, present=True)

    updated = await warm.run(low, signals, target=target)

    # Social axis is pulled toward the (higher) baseline — only lift_toward touches it
    # here (presence already saturated apart, so the displacement is observable).
    assert updated.social > low.social
    # And valence is pulled up out of the dip beyond the bare positive delta alone.
    assert updated.valence > low.valence


async def test_cold_message_does_not_pull_toward_baseline() -> None:
    # The pull is asymmetric: a cold/rude message lowers (weakly) but never charges
    # Bob UP toward baseline — only warmth displaces the low.
    disp = Disposition(optimism=0.8, resilience=0.7)
    cold = _disposed(sentiment="negative", moment=_daytime(), disposition=disp)
    low = Mood(valence=-0.6, social=-0.5)
    target = Mood(valence=0.4, social=0.55)
    signals = TextSignals(text="you're useless", message_count=1, present=True)

    updated = await cold.run(low, signals, target=target)

    # Cold turn dips valence further (weakly) and never tugs mood up to baseline:
    # social moves ONLY by the presence step (+0.15), not by any lift_toward pull.
    assert updated.valence < low.valence
    assert updated.social == pytest.approx(low.social + 0.15)


async def test_no_target_keeps_pure_delta_behaviour() -> None:
    # Backward-compatible: without a target the use-case applies only the
    # (now disposition-scaled) delta and never calls lift_toward.
    disp = Disposition(optimism=0.8, resilience=0.7)
    warm = _disposed(sentiment="positive", moment=_daytime(), disposition=disp)
    low = Mood(valence=-0.6, social=-0.5)
    signals = TextSignals(text="nice", message_count=1, present=True)

    updated = await warm.run(low, signals)

    # social only moved by the presence step (+), not pulled toward any baseline.
    assert updated.social == pytest.approx(low.social + 0.15)
