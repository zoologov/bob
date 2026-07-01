# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure volatility-judgment wire protocol (BOB-057 .1).

Covers the pure domain pieces of the verify-when-volatile seam: the Tier-0 prompt
builder (folds the incoming message + recent thread), the conservative reply parser
(model output -> ``VolatilityVerdict``, robust to whitespace/case, DEFAULTING to
``needs_check=False`` on an ambiguous/negative/garbled reply — don't check when
unsure), and the frozen value types.
"""

from __future__ import annotations

import pytest

from bob.domain.personality.volatility_judgment import (
    VOLATILITY_JUDGE_SYSTEM_PROMPT,
    VolatilityContext,
    VolatilityJudgeParseError,
    VolatilityVerdict,
    build_volatility_user_prompt,
    parse_volatility_verdict,
)


def _context(
    *,
    text: str = "какая сейчас ставка ЦБ?",
    recent_thread: str = "Лёша: привет\nbob: здравствуй",
) -> VolatilityContext:
    return VolatilityContext(text=text, recent_thread=recent_thread)


# --- prompt builder ----------------------------------------------------------


def test_prompt_includes_message_and_thread() -> None:
    prompt = build_volatility_user_prompt(
        _context(text="сколько стоит биткоин?", recent_thread="Лёша: йо\nbob: йо")
    )
    assert "сколько стоит биткоин?" in prompt
    assert "Лёша: йо" in prompt


def test_prompt_handles_empty_thread() -> None:
    prompt = build_volatility_user_prompt(_context(recent_thread=""))
    assert "какая сейчас ставка ЦБ?" in prompt


def test_system_prompt_is_conservative() -> None:
    # The heart of US-2 «не зануда»: the contract must state the yes-only-when-both
    # rule and offer both positive and negative examples.
    assert "needs_check" in VOLATILITY_JUDGE_SYSTEM_PROMPT


# --- parser: well-formed -----------------------------------------------------


def test_parses_positive_verdict_with_query_and_topic() -> None:
    verdict = parse_volatility_verdict(
        "needs_check: yes\n"
        "query: текущая ключевая ставка ЦБ РФ 2026\n"
        "topic: свежая ставка ЦБ"
    )
    assert verdict.needs_check is True
    assert verdict.query == "текущая ключевая ставка ЦБ РФ 2026"
    assert verdict.topic == "свежая ставка ЦБ"


def test_parses_negative_verdict() -> None:
    verdict = parse_volatility_verdict("needs_check: no\nquery: \ntopic: ")
    assert verdict.needs_check is False
    assert verdict.query == ""
    assert verdict.topic == ""


def test_parse_is_case_and_whitespace_tolerant() -> None:
    verdict = parse_volatility_verdict(
        "  NEEDS_CHECK :  Yes \n  QUERY :  цена нефти brent сегодня \n  TOPIC : цена нефти "
    )
    assert verdict.needs_check is True
    assert verdict.query == "цена нефти brent сегодня"
    assert verdict.topic == "цена нефти"


# --- parser: conservative default (garbled/ambiguous -> False) ---------------


def test_garbled_reply_defaults_to_no_check() -> None:
    # No recognisable needs_check label at all → conservative False (don't check).
    assert parse_volatility_verdict("я не уверен, honestly").needs_check is False


def test_ambiguous_bool_defaults_to_no_check() -> None:
    # A needs_check value that is neither yes nor no → conservative False.
    assert parse_volatility_verdict("needs_check: maybe\nquery: x").needs_check is False


def test_empty_reply_defaults_to_no_check() -> None:
    assert parse_volatility_verdict("").needs_check is False


def test_yes_without_query_raises() -> None:
    # An affirmative verdict with no actionable search query is unusable — a real
    # failure the infra propagates so the caller safe-defaults (still no check).
    with pytest.raises(VolatilityJudgeParseError):
        parse_volatility_verdict("needs_check: yes\nquery: \ntopic: свежая ставка")


# --- value types -------------------------------------------------------------


def test_verdict_is_frozen() -> None:
    verdict = VolatilityVerdict(needs_check=False, query="", topic="")
    with pytest.raises((AttributeError, TypeError)):
        verdict.needs_check = True  # type: ignore[misc]


def test_context_is_frozen() -> None:
    ctx = _context()
    with pytest.raises((AttributeError, TypeError)):
        ctx.text = "изменено"  # type: ignore[misc]
