# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the hybrid reply-tier selector (BOB-006 BEAD-02).

The selector decides which tier (and thus which model) serves a user reply:

- **flash** (Tier 0, fast) for casual/short messages — the responsive default;
- **plus** (Tier 1, quality) when the message looks complex/long/tool-needing.

The classification is a pure, deterministic heuristic on the *incoming user
message* (no extra LLM round-trip): length, multiple questions, code presence,
or depth/complexity keywords escalate to the quality model; everything else
stays on flash. A turn that needs tools always prefers the quality model.
"""

from __future__ import annotations

import pytest

from bob.application.router.reply_tier_selector import (
    _LONG_MESSAGE_CHARS,
    _MAX_CASUAL_QUESTIONS,
    _TIER_API,
    _TIER_LOCAL,
    select_reply_tier,
)


def test_casual_short_message_selects_flash() -> None:
    # A short, casual greeting needs no depth — stay on the fast flash model.
    assert select_reply_tier("привет, как дела?") == _TIER_LOCAL


def test_very_short_message_selects_flash() -> None:
    assert select_reply_tier("ок") == _TIER_LOCAL


def test_long_message_selects_plus() -> None:
    # A message well past the length threshold escalates to the quality model.
    long_message = "слово " * 80
    assert select_reply_tier(long_message) == _TIER_API


def test_multiple_questions_selects_plus() -> None:
    # Several questions in one turn signal a thread that wants depth.
    assert select_reply_tier("кто ты? откуда ты? что умеешь?") == _TIER_API


def test_code_block_selects_plus() -> None:
    # A fenced code block signals a coding turn — route to the quality model.
    assert select_reply_tier("посмотри:\n```python\nprint('hi')\n```") == _TIER_API


def test_depth_keyword_selects_plus() -> None:
    # Russian depth/complexity keywords escalate even on a short message.
    for keyword_message in (
        "объясни рекурсию",
        "расскажи подробно про сон",
        "проанализируй этот текст",
        "сравни кофе и чай",
        "напиши код сортировки",
        "разбери эту ошибку",
        "почему небо синее",
        "как устроен мозг",
    ):
        assert select_reply_tier(keyword_message) == _TIER_API, keyword_message


def test_keyword_match_is_case_insensitive() -> None:
    assert select_reply_tier("ОБЪЯСНИ это") == _TIER_API


def test_keyword_must_be_a_whole_word() -> None:
    # A keyword embedded in a larger word must NOT trigger escalation
    # ("сравнительно" contains "сравни" but is not a request to compare).
    assert select_reply_tier("это сравнительно просто") == _TIER_LOCAL


def test_tool_needing_turn_forces_plus() -> None:
    # When the turn needs tools, the quality model is preferred (more reliable
    # tool-calling) regardless of how casual the message text looks.
    assert select_reply_tier("ок", needs_tools=True) == _TIER_API


def test_selection_is_deterministic() -> None:
    message = "объясни подробно как это работает"
    first = select_reply_tier(message)
    second = select_reply_tier(message)
    assert first == second == _TIER_API


# --- Boundary / edge cases (BOB-006 BEAD-03 hardening) ------------------------


def test_empty_message_selects_flash() -> None:
    # An empty turn carries no escalation signal — it must not crash and must
    # stay on the fast default rather than spuriously escalating.
    assert select_reply_tier("") == _TIER_LOCAL


def test_whitespace_only_message_selects_flash() -> None:
    assert select_reply_tier("   \n\t  ") == _TIER_LOCAL


def test_message_at_exact_length_threshold_stays_flash() -> None:
    # The threshold is strict ("> _LONG_MESSAGE_CHARS"): a message of exactly the
    # threshold length is NOT long, so it stays on flash (off-by-one boundary).
    message = "a" * _LONG_MESSAGE_CHARS
    assert len(message) == _LONG_MESSAGE_CHARS
    assert select_reply_tier(message) == _TIER_LOCAL


def test_message_one_char_over_threshold_escalates_to_plus() -> None:
    message = "a" * (_LONG_MESSAGE_CHARS + 1)
    assert select_reply_tier(message) == _TIER_API


def test_single_question_stays_flash() -> None:
    # One question mark is casual (at the allowed maximum); it must not escalate.
    assert _MAX_CASUAL_QUESTIONS == 1
    assert select_reply_tier("как дела?") == _TIER_LOCAL


def test_question_count_just_over_the_casual_maximum_escalates() -> None:
    # One more question than the casual maximum tips the turn into the quality tier.
    message = "?" * (_MAX_CASUAL_QUESTIONS + 1)
    assert select_reply_tier(message) == _TIER_API


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("спасибо!", _TIER_LOCAL),
        ("да", _TIER_LOCAL),
        ("ну норм 😄", _TIER_LOCAL),
        ("объясни почему", _TIER_API),
        ("сравни X и Y подробно", _TIER_API),
    ],
)
def test_tier_selection_table(message: str, expected: int) -> None:
    # A small table pinning representative casual vs. complex turns.
    assert select_reply_tier(message) == expected


def test_needs_tools_overrides_a_long_complex_message_still_plus() -> None:
    # needs_tools and complexity both point to plus; the result is unambiguously
    # the quality tier (no contradictory downgrade).
    assert select_reply_tier("объясни " * 50, needs_tools=True) == _TIER_API


def test_unicode_emoji_only_message_does_not_crash_and_stays_flash() -> None:
    assert select_reply_tier("🔥🔥🔥") == _TIER_LOCAL
