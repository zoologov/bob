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


# --- 🔴 US-2 «НЕ ЗАНУДА»: the representative anti-bore table (headline) --------
#
# The generous "must be False" set is the anti-bore GUARANTEE: casual banter,
# greetings, opinions/feelings, jokes, hypotheticals, stable facts (history, math,
# geography, definitions) and questions about Bob himself / his memory must NEVER
# trip a verify pass. Each row is a representative conservative Tier-0 reply for that
# category (plus the sloppy/ambiguous/garbled forms a real model emits) — ALL must
# parse to ``needs_check=False`` with an empty query/topic and no exception raised.
# If a future parser tweak ever flipped an ambiguous reply to True, this table breaks
# loudly (Bob would become «зануда»).

_MUST_BE_FALSE_OUTPUTS: tuple[tuple[str, str], ...] = (
    # — well-formed conservative "no" per benign category —
    ("greeting_hi", "needs_check: no\nquery:\ntopic:"),
    ("greeting_morning", "needs_check: no"),
    ("smalltalk_howareyou", "needs_check: no\nquery:"),
    ("smalltalk_bored", "needs_check: no"),
    ("opinion_autumn", "needs_check: no"),
    ("feeling_mood", "needs_check: no"),
    ("joke_anecdote", "needs_check: no"),
    ("joke_pun", "needs_check: no"),
    ("hypothetical_iffly", "needs_check: no"),
    ("stable_history_date", "needs_check: no"),  # «когда была Куликовская битва?»
    ("stable_math_sum", "needs_check: no"),  # «сколько будет 2+2?»
    ("stable_geography_capital", "needs_check: no"),  # «столица Франции?»
    ("stable_definition_recursion", "needs_check: no"),  # «что такое рекурсия?»
    ("bob_self_favourite_colour", "needs_check: no"),  # вопрос про самого Боба
    ("bob_memory_yesterday", "needs_check: no"),  # «помнишь, о чём вчера говорили?»
    ("bob_remembers_me", "needs_check: no"),
    # — sloppy / ambiguous / garbled forms that MUST default to False —
    ("bare_no_word", "no"),
    ("russian_no", "needs_check: нет"),
    ("false_token", "needs_check: false"),
    ("maybe_is_not_yes", "needs_check: maybe\nquery: что-то"),
    ("unlabelled_prose", "по-моему, проверять не нужно"),
    ("empty_reply", ""),
    ("whitespace_reply", "   \n  \t "),
    ("no_label_with_query_only", "query: случайный текст без вердикта"),
)


@pytest.mark.parametrize(
    "raw",
    [pytest.param(raw, id=name) for name, raw in _MUST_BE_FALSE_OUTPUTS],
)
def test_must_be_false_set_never_triggers_a_check(raw: str) -> None:
    # 🔴 The headline anti-bore lock: none of these benign / ambiguous replies may
    # ever ask Bob to hit the net — conservative False, no query, no topic.
    verdict = parse_volatility_verdict(raw)
    assert verdict.needs_check is False
    assert verdict.query == ""
    assert verdict.topic == ""


def test_must_be_false_set_is_generous() -> None:
    # A regression guard on the guarantee itself: the anti-bore set stays broad (it is
    # the anti-«зануда» floor — shrinking it silently would weaken US-2).
    assert len(_MUST_BE_FALSE_OUTPUTS) >= 20


# --- 🔴 US-2: the volatile categories that MAY be checked ---------------------
#
# The complementary "may be True" set: genuinely fast-decaying facts where a fresh
# check materially changes the answer. A well-formed affirmative reply for each must
# parse to ``needs_check=True`` and PRESERVE the model's actionable search query.

_MAY_BE_TRUE_OUTPUTS: tuple[tuple[str, str, str], ...] = (
    (
        "ofz_rates",
        "needs_check: yes\nquery: доходность ОФЗ сегодня\ntopic: ставки ОФЗ",
        "доходность ОФЗ сегодня",
    ),
    (
        "bitcoin_price",
        "needs_check: yes\nquery: курс биткоина сегодня USD\ntopic: курс BTC",
        "курс биткоина сегодня USD",
    ),
    (
        "latest_version",
        "needs_check: yes\nquery: последняя версия Python\ntopic: версия Python",
        "последняя версия Python",
    ),
    (
        "who_is_in_power",
        "needs_check: yes\nquery: кто сейчас президент Франции\ntopic: власть Франции",
        "кто сейчас президент Франции",
    ),
    (
        "weather_today",
        "needs_check: yes\nquery: погода в Москве сегодня\ntopic: погода",
        "погода в Москве сегодня",
    ),
    (
        "fx_rate",
        "needs_check: yes\nquery: курс доллара к рублю сейчас\ntopic: курс доллара",
        "курс доллара к рублю сейчас",
    ),
)


@pytest.mark.parametrize(
    ("raw", "expected_query"),
    [
        pytest.param(raw, query, id=name)
        for name, raw, query in _MAY_BE_TRUE_OUTPUTS
    ],
)
def test_may_be_true_set_checks_and_preserves_the_query(
    raw: str, expected_query: str
) -> None:
    # The volatile side: an affirmative reply yields a check with the model's query
    # intact (the query is what the direct web_search runs in .2).
    verdict = parse_volatility_verdict(raw)
    assert verdict.needs_check is True
    assert verdict.query == expected_query
    assert verdict.topic != ""


def test_system_prompt_enumerates_benign_and_volatile_signals() -> None:
    # 🔴 US-2 at the CONTRACT: the conservative prompt must both (a) list the volatile
    # signals that MAY warrant a check and (b) name the benign categories that must not
    # — this is what steers the Tier-0 model away from being a «зануда».
    prompt = VOLATILITY_JUDGE_SYSTEM_PROMPT
    for volatile_signal in ("ставк", "цен", "курс", "сейчас", "погода", "версии"):
        assert volatile_signal in prompt
    for benign_signal in ("мнения", "шутки", "болтовня", "история", "память"):
        assert benign_signal in prompt
    # The conservative tie-break must be spelled out: unsure → no.
    assert "Сомневаешься — no" in prompt


# --- value types -------------------------------------------------------------


def test_verdict_is_frozen() -> None:
    verdict = VolatilityVerdict(needs_check=False, query="", topic="")
    with pytest.raises((AttributeError, TypeError)):
        verdict.needs_check = True  # type: ignore[misc]


def test_context_is_frozen() -> None:
    ctx = _context()
    with pytest.raises((AttributeError, TypeError)):
        ctx.text = "изменено"  # type: ignore[misc]
