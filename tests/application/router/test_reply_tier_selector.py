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

from bob.application.router.reply_tier_selector import (
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
