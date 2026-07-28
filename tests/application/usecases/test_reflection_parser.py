# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for HeuristicReflectionParser — deterministic reflection -> signal parse.

A conservative keyword heuristic (no LLM, no I/O): the default realisation of the
:class:`ReflectionParser` port. It fires only when the reflection mentions a topic
Bob actually has a taste for AND carries a clear sentiment polarity. Anything
vague yields ``None`` so the relevance gate keeps the soul still. Bilingual
markers (ru/en) since Bob's persona language is Russian.
"""

from __future__ import annotations

from bob.personality.usecases.reflection_parser import HeuristicReflectionParser

_TOPICS = ("jazz", "coffee", "тишина")


def test_positive_mention_yields_a_positive_nudge() -> None:
    # Arrange
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("I really love jazz, it lifts me.", topics=_TOPICS)

    # Assert
    assert signal is not None
    assert signal.topic == "jazz"
    assert signal.nudge > 0.0


def test_negative_mention_yields_a_negative_nudge() -> None:
    # Arrange
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("Honestly I hate coffee these days.", topics=_TOPICS)

    # Assert
    assert signal is not None
    assert signal.topic == "coffee"
    assert signal.nudge < 0.0


def test_russian_positive_marker_is_recognised() -> None:
    # Arrange: persona language is Russian.
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("Мне нравится тишина по вечерам.", topics=_TOPICS)

    # Assert
    assert signal is not None
    assert signal.topic == "тишина"
    assert signal.nudge > 0.0


def test_topic_without_sentiment_is_no_signal() -> None:
    # Arrange: a bare mention with no polarity word.
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("I thought about jazz today.", topics=_TOPICS)

    # Assert: no clear sentiment -> relevance gate (None).
    assert signal is None


def test_sentiment_without_known_topic_is_no_signal() -> None:
    # Arrange: strong sentiment but about nothing Bob has a taste for.
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("I love long walks.", topics=_TOPICS)

    # Assert
    assert signal is None


def test_empty_topics_is_no_signal() -> None:
    # Arrange
    parser = HeuristicReflectionParser()

    # Act
    signal = parser.parse("I love jazz.", topics=())

    # Assert
    assert signal is None
