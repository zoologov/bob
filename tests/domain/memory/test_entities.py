# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure memory domain entities (no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.memory.entities import EpisodicEvent, SemanticFact


def _ts() -> datetime:
    return datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


def test_episodic_event_holds_its_fields() -> None:
    # Arrange / Act
    event = EpisodicEvent(
        ts=_ts(),
        event_type="message",
        content="hello bob",
        mood_snapshot="calm",
        tags=("greeting", "user"),
    )

    # Assert
    assert event.event_type == "message"
    assert event.content == "hello bob"
    assert event.mood_snapshot == "calm"
    assert event.tags == ("greeting", "user")


def test_episodic_event_is_immutable() -> None:
    # Arrange
    event = EpisodicEvent(ts=_ts(), event_type="message", content="x")

    # Act / Assert: frozen dataclass rejects attribute assignment.
    with pytest.raises(AttributeError):
        event.content = "mutated"  # type: ignore[misc]


def test_episodic_event_defaults_are_empty_not_none() -> None:
    # Arrange / Act
    event = EpisodicEvent(ts=_ts(), event_type="tick", content="beat")

    # Assert: optional fields default to safe empties, never a shared mutable.
    assert event.mood_snapshot is None
    assert event.tags == ()


def test_episodic_event_requires_timezone_aware_ts() -> None:
    # Arrange / Act / Assert: naive datetimes are rejected (Clock is tz-aware).
    with pytest.raises(ValueError, match="timezone-aware"):
        EpisodicEvent(
            ts=datetime(2026, 6, 18, 12, 0, 0),  # noqa: DTZ001 — intentional naive ts
            event_type="message",
            content="x",
        )


def test_semantic_fact_holds_its_fields() -> None:
    # Arrange / Act
    fact = SemanticFact(
        ts=_ts(),
        category="preference",
        content="bob likes jazz",
        confidence=0.8,
    )

    # Assert
    assert fact.category == "preference"
    assert fact.content == "bob likes jazz"
    assert fact.confidence == pytest.approx(0.8)


def test_semantic_fact_is_immutable() -> None:
    # Arrange
    fact = SemanticFact(ts=_ts(), category="fact", content="sky is blue")

    # Act / Assert
    with pytest.raises(AttributeError):
        fact.content = "mutated"  # type: ignore[misc]


def test_semantic_fact_rejects_out_of_range_confidence() -> None:
    # Arrange / Act / Assert: confidence is a [0, 1] probability.
    with pytest.raises(ValueError, match="confidence"):
        SemanticFact(ts=_ts(), category="fact", content="x", confidence=1.5)
