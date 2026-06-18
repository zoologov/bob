# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for TasteEngine — deterministic taste scoring (no LLM, no I/O)."""

from __future__ import annotations

import pytest

from bob.domain.personality.taste import TasteAxis, TasteEngine, Verdict


def test_taste_axis_holds_its_fields() -> None:
    # Arrange / Act
    axis = TasteAxis(name="jazz", value=0.6, conviction=0.8, experience_count=12)

    # Assert
    assert axis.name == "jazz"
    assert axis.value == pytest.approx(0.6)
    assert axis.conviction == pytest.approx(0.8)
    assert axis.experience_count == 12


def test_taste_axis_is_immutable() -> None:
    # Arrange
    axis = TasteAxis(name="jazz", value=0.6, conviction=0.8)

    # Act / Assert
    with pytest.raises(AttributeError):
        axis.value = 0.1  # type: ignore[misc]


def test_taste_axis_rejects_out_of_range_value() -> None:
    # Arrange / Act / Assert: value (liking) is bounded to [-1, 1].
    with pytest.raises(ValueError, match="value"):
        TasteAxis(name="jazz", value=2.0, conviction=0.5)


def test_taste_axis_rejects_out_of_range_conviction() -> None:
    # Arrange / Act / Assert: conviction is a [0, 1] strength.
    with pytest.raises(ValueError, match="conviction"):
        TasteAxis(name="jazz", value=0.5, conviction=1.5)


def test_taste_axis_rejects_negative_experience_count() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="experience_count"):
        TasteAxis(name="jazz", value=0.5, conviction=0.5, experience_count=-1)


def _engine() -> TasteEngine:
    return TasteEngine(
        axes=(
            TasteAxis(name="jazz", value=0.9, conviction=0.9, experience_count=20),
            TasteAxis(name="coffee", value=0.4, conviction=0.6, experience_count=5),
            TasteAxis(name="rain", value=-0.85, conviction=0.9, experience_count=8),
            TasteAxis(name="meetings", value=-0.3, conviction=0.5, experience_count=3),
        )
    )


def test_score_strong_positive_axis_is_love() -> None:
    # Arrange
    engine = _engine()

    # Act
    verdict = engine.score("jazz")

    # Assert
    assert verdict is Verdict.LOVE


def test_score_mild_positive_axis_is_like() -> None:
    # Arrange / Act
    verdict = _engine().score("coffee")

    # Assert
    assert verdict is Verdict.LIKE


def test_score_strong_negative_axis_is_hate() -> None:
    # Arrange / Act
    verdict = _engine().score("rain")

    # Assert
    assert verdict is Verdict.HATE


def test_score_mild_negative_axis_is_dislike() -> None:
    # Arrange / Act
    verdict = _engine().score("meetings")

    # Assert
    assert verdict is Verdict.DISLIKE


def test_score_unknown_topic_is_neutral() -> None:
    # Arrange / Act: nothing Bob has an opinion on yet.
    verdict = _engine().score("quantum chromodynamics")

    # Assert
    assert verdict is Verdict.NEUTRAL


def test_score_is_case_insensitive() -> None:
    # Arrange / Act
    verdict = _engine().score("JAZZ")

    # Assert: topic matching ignores case.
    assert verdict is Verdict.LOVE


def test_score_is_deterministic() -> None:
    # Arrange
    engine = _engine()

    # Act / Assert: same object → same verdict, no randomness.
    assert engine.score("coffee") is engine.score("coffee")


def test_low_conviction_strong_value_softens_to_like_not_love() -> None:
    # Arrange: Bob barely-tested liking — high value but weak conviction.
    engine = TasteEngine(
        axes=(TasteAxis(name="sushi", value=0.95, conviction=0.1, experience_count=1),)
    )

    # Act
    verdict = engine.score("sushi")

    # Assert: without conviction, a strong value cannot reach LOVE.
    assert verdict is Verdict.LIKE
