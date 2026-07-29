# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the staleness-judge prompt + parser — the model-facing half of the seam.

The pure verdict lives in :mod:`bob.presence.staleness`; here we pin the prompt builder
(what the model sees) and the parser (how a labelled reply maps to a ``StalenessReading``).
🔴 Fail-safe: an unreadable / missing field reads as ``False`` («ничего не сместилось»), so a
garbled reply lets the pure gate SEND rather than silently drop Bob's reply.
"""

from __future__ import annotations

from bob.presence.staleness import ArrivedMessage, StalenessContext
from bob.presence.staleness_judgment import (
    STALENESS_JUDGE_SYSTEM_PROMPT,
    build_staleness_user_prompt,
    parse_staleness_reading,
)


def _ctx(*arrivals: ArrivedMessage) -> StalenessContext:
    return StalenessContext(drafted="Кофе лучше всего утром", newly_arrived=arrivals)


def _arrival(
    *,
    text: str = "а по-моему вечером",
    mentions_bob: bool = False,
    reply_to_bob: bool = False,
    from_draft_author: bool = False,
) -> ArrivedMessage:
    return ArrivedMessage(
        sender_id=9,
        text=text,
        mentions_bob=mentions_bob,
        reply_to_bob=reply_to_bob,
        from_draft_author=from_draft_author,
    )


# ── build_staleness_user_prompt ───────────────────────────────────────────────────


def test_prompt_includes_draft_and_arrivals() -> None:
    prompt = build_staleness_user_prompt(
        _ctx(_arrival(text="уже ответил Норман"))
    )
    assert "Кофе лучше всего утром" in prompt
    assert "уже ответил Норман" in prompt


def test_prompt_marks_a_fresh_direct_address() -> None:
    prompt = build_staleness_user_prompt(
        _ctx(_arrival(text="Боб, а ты что скажешь?", mentions_bob=True, reply_to_bob=True))
    )
    assert "упоминает тебя" in prompt
    assert "ответ тебе" in prompt


def test_prompt_marks_a_same_author_followup() -> None:
    prompt = build_staleness_user_prompt(
        _ctx(_arrival(text="в смысле для эспрессо", from_draft_author=True))
    )
    assert "тот же автор" in prompt


def test_prompt_handles_an_empty_burst() -> None:
    assert "(ничего)" in build_staleness_user_prompt(_ctx())


def test_system_prompt_states_the_mutual_exclusion() -> None:
    # 🔴🔴 The judge contract: answered/closed are mutually exclusive with new_question.
    assert "ВЗАИМОИСКЛЮЧАЮТ" in STALENESS_JUDGE_SYSTEM_PROMPT


# ── parse_staleness_reading ───────────────────────────────────────────────────────


def test_parses_all_flags() -> None:
    reading = parse_staleness_reading(
        "answered: yes\nclosed: no\nclarified: yes\nnew_question: no"
    )
    assert reading.answered_by_other is True
    assert reading.topic_closed is False
    assert reading.same_author_clarified is True
    assert reading.new_direct_question is False


def test_parses_russian_and_case_insensitive_tokens() -> None:
    reading = parse_staleness_reading(
        "Answered: ДА\nClosed: нет\nClarified: НЕТ\nNew_question: ДА"
    )
    assert reading.answered_by_other is True
    assert reading.topic_closed is False
    assert reading.new_direct_question is True


def test_garbled_reply_reads_as_nothing_shifted() -> None:
    # Fail-safe: every field unreadable → all False → the gate SENDs (never a silent drop).
    reading = parse_staleness_reading("понятия не имею, что тут случилось")
    assert reading.answered_by_other is False
    assert reading.topic_closed is False
    assert reading.same_author_clarified is False
    assert reading.new_direct_question is False


def test_missing_field_defaults_to_false() -> None:
    reading = parse_staleness_reading("answered: yes")
    assert reading.answered_by_other is True
    assert reading.new_direct_question is False
    assert reading.topic_closed is False
