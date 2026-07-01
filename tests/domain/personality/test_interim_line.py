# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the interim-line seam — pure prompt + cleaner (BOB-057 .3, US-3b).

When the pre-answer verify decides to check, Bob sends a LIVE, ADDRESSED one-liner
in his own voice naming WHAT he checks and WHO he talks to. The model-facing half
is pure: the system prompt states the one-liner contract, the user prompt folds
``topic`` + ``sender_name``, and :func:`clean_interim_line` keeps the reply a single
tidy line (first line, unquoted, bounded) — no preamble, no multi-line ramble.
"""

from __future__ import annotations

from bob.domain.personality.interim_line import (
    INTERIM_LINE_SYSTEM_PROMPT,
    build_interim_line_user_prompt,
    clean_interim_line,
)


def test_user_prompt_folds_topic_and_sender_name() -> None:
    prompt = build_interim_line_user_prompt(topic="свежие ставки", sender_name="Лёша")

    assert "свежие ставки" in prompt
    assert "Лёша" in prompt


def test_user_prompt_survives_a_missing_sender_name() -> None:
    # An unknown sender (empty name) still yields a usable topic-only prompt.
    prompt = build_interim_line_user_prompt(topic="курс биткоина", sender_name="")

    assert "курс биткоина" in prompt


def test_system_prompt_demands_a_short_addressed_one_liner() -> None:
    # The persona contract: one live line in Bob's voice, no preamble.
    assert "одн" in INTERIM_LINE_SYSTEM_PROMPT.casefold()  # "одну строку"/"одной"


def test_system_prompt_reads_for_a_search_query_not_only_a_fact_check() -> None:
    # BOB-060 .2: the interim prompt is now shared by BOTH paths — the verify
    # «сверка факта» and the tool-loop «поиск по запросу». It must frame the moment
    # as Bob going to LOOK something up in the net (works for a search query too),
    # not exclusively as verifying a fact. Keep it a tight, in-voice one-liner.
    lowered = INTERIM_LINE_SYSTEM_PROMPT.casefold()

    assert "сет" in lowered  # in the net
    assert "глян" in lowered  # "идёшь глянуть" — reads for a search, not only a check
    assert "одн" in lowered  # still a single short line


def test_clean_takes_the_first_nonempty_line() -> None:
    raw = "\n  Лёш, гляну свежие ставки, секунду 🙂\nвторая строка лишняя"

    assert clean_interim_line(raw) == "Лёш, гляну свежие ставки, секунду 🙂"


def test_clean_strips_wrapping_quotes() -> None:
    assert clean_interim_line('"момент, проверю"') == "момент, проверю"
    assert clean_interim_line("«секунду, гляну»") == "секунду, гляну"


def test_clean_empty_reply_is_empty() -> None:
    assert clean_interim_line("   \n  ") == ""


def test_clean_bounds_a_runaway_line() -> None:
    raw = "а" * 500

    cleaned = clean_interim_line(raw)

    assert 0 < len(cleaned) <= 160
