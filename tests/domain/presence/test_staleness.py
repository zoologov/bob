# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the staleness/merge-gate — the pure «reassess the drafted reply» core.

The gate answers ONE question deterministically: given a reply Bob drafted and what
landed in the chat while he was drafting it, does he still SEND it, REWRITE it against
a clarification, DROP_TO_LIKE (react instead of a now-redundant reply), or MERGE a
fresh direct question into one reply? The LLM/structural judge VERBALISES the shift
(:class:`StalenessReading`); this pure core DECIDES the outcome — mirroring
``decide_from_reading`` — so the verdict is pinned exactly and mutation-tested hard.
"""

from __future__ import annotations

from bob.presence.staleness import (
    ArrivedMessage,
    StalenessGate,
    StalenessOutcome,
    StalenessReading,
    decide_staleness,
    nothing_arrived,
)


def _reading(
    *,
    answered_by_other: bool = False,
    topic_closed: bool = False,
    same_author_clarified: bool = False,
    new_direct_question: bool = False,
) -> StalenessReading:
    return StalenessReading(
        answered_by_other=answered_by_other,
        topic_closed=topic_closed,
        same_author_clarified=same_author_clarified,
        new_direct_question=new_direct_question,
        reason="test",
    )


def _arrived() -> ArrivedMessage:
    return ArrivedMessage(
        sender_id=7,
        text="что-то приехало",
        mentions_bob=False,
        reply_to_bob=False,
        from_draft_author=False,
    )


# ── decide_staleness: the pure verdict core ──────────────────────────────────────


def test_quiet_shift_sends_as_drafted() -> None:
    # Arrange: nothing semantically changed — every flag is False.
    reading = _reading()

    # Act
    outcome = decide_staleness(reading)

    # Assert: the draft is still fresh → SEND.
    assert outcome is StalenessOutcome.SEND


def test_answered_by_other_drops_to_like() -> None:
    # Arrange: someone else already answered the point Bob drafted.
    reading = _reading(answered_by_other=True)

    # Act / Assert: the reply is now redundant → react instead of speaking.
    assert decide_staleness(reading) is StalenessOutcome.DROP_TO_LIKE


def test_topic_closed_drops_to_like() -> None:
    # Arrange: the thread moved on / the question was withdrawn.
    reading = _reading(topic_closed=True)

    # Act / Assert
    assert decide_staleness(reading) is StalenessOutcome.DROP_TO_LIKE


def test_new_direct_question_merges() -> None:
    # Arrange: a fresh direct question to Bob landed on top of the draft.
    reading = _reading(new_direct_question=True)

    # Act / Assert: fold both into ONE reply (dedup) → MERGE.
    assert decide_staleness(reading) is StalenessOutcome.MERGE


def test_same_author_clarification_rewrites() -> None:
    # Arrange: the original asker refined/corrected what they meant.
    reading = _reading(same_author_clarified=True)

    # Act / Assert: regenerate the reply against the clarification → REWRITE.
    assert decide_staleness(reading) is StalenessOutcome.REWRITE


def test_drop_precedes_merge() -> None:
    # Arrange: the point is moot (topic closed) AND a new question arrived.
    reading = _reading(topic_closed=True, new_direct_question=True)

    # Act / Assert: a moot draft is dropped before any merge is considered.
    assert decide_staleness(reading) is StalenessOutcome.DROP_TO_LIKE


def test_answered_by_other_precedes_rewrite() -> None:
    # Arrange: answered by someone else AND the author clarified.
    reading = _reading(answered_by_other=True, same_author_clarified=True)

    # Act / Assert: redundancy wins — no point rewriting a moot reply.
    assert decide_staleness(reading) is StalenessOutcome.DROP_TO_LIKE


def test_new_question_precedes_rewrite() -> None:
    # Arrange: a fresh direct question AND a same-author clarification.
    reading = _reading(new_direct_question=True, same_author_clarified=True)

    # Act / Assert: one merged reply covers the new question — MERGE beats REWRITE.
    assert decide_staleness(reading) is StalenessOutcome.MERGE


# ── nothing_arrived: the cheap structural short-circuit ──────────────────────────


def test_nothing_arrived_true_for_empty() -> None:
    assert nothing_arrived(()) is True


def test_nothing_arrived_false_when_something_landed() -> None:
    assert nothing_arrived((_arrived(),)) is False


# ── StalenessGate facade ─────────────────────────────────────────────────────────


def test_gate_sends_when_nothing_arrived() -> None:
    # Arrange: nothing landed → the judge is never consulted (reading irrelevant).
    gate = StalenessGate()

    # Act
    outcome = gate.reassess((), _reading(answered_by_other=True))

    # Assert: an empty burst is always fresh → SEND, ignoring any stale reading.
    assert outcome is StalenessOutcome.SEND


def test_gate_fails_safe_to_send_without_a_reading() -> None:
    # Arrange: something landed but the judge produced no reading (unavailable/failed).
    gate = StalenessGate()

    # Act
    outcome = gate.reassess((_arrived(),), None)

    # Assert: fail-safe — never silently drop; send the draft as-is.
    assert outcome is StalenessOutcome.SEND


def test_gate_delegates_to_the_verdict_core_when_context_shifted() -> None:
    # Arrange: something landed AND the judge read it as answered-by-other.
    gate = StalenessGate()

    # Act
    outcome = gate.reassess((_arrived(),), _reading(answered_by_other=True))

    # Assert: the gate delegates to decide_staleness → DROP_TO_LIKE.
    assert outcome is StalenessOutcome.DROP_TO_LIKE
