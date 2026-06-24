# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты домена brevity (BOB-024): answer-demand + verbosity.

Чистый домен, детерминированный: стохастика входит через явный ``roll`` —
рандома внутри нет, поэтому тесты задают исход одним числом.
"""

from __future__ import annotations

import pytest

from bob.domain.personality.brevity import (
    AnswerDemand,
    BrevityThresholds,
    Verbosity,
    classify_answer_demand,
    decide_verbosity,
)
from bob.domain.personality.expression import FormHint

# --- classify_answer_demand --------------------------------------------------


class TestClassifyAnswerDemandLow:
    """LOW — закрытые/короткие реплики, не требующие развёрнутости."""

    def test_yes_no_question_is_low(self) -> None:
        assert classify_answer_demand(text="получилось?") is AnswerDemand.LOW

    def test_presence_check_is_low(self) -> None:
        assert classify_answer_demand(text="ты тут?") is AnswerDemand.LOW

    def test_when_question_is_low(self) -> None:
        assert classify_answer_demand(text="во сколько?") is AnswerDemand.LOW

    def test_very_short_statement_is_low(self) -> None:
        assert classify_answer_demand(text="ага") is AnswerDemand.LOW

    def test_english_yes_no_is_low(self) -> None:
        assert classify_answer_demand(text="did it work?") is AnswerDemand.LOW


class TestClassifyAnswerDemandHigh:
    """HIGH — открытые/глубокие запросы, требующие развёрнутости."""

    def test_why_question_is_high(self) -> None:
        assert classify_answer_demand(text="почему так вышло?") is AnswerDemand.HIGH

    def test_how_question_is_high(self) -> None:
        assert (
            classify_answer_demand(text="как это вообще работает?")
            is AnswerDemand.HIGH
        )

    def test_opinion_request_is_high(self) -> None:
        assert (
            classify_answer_demand(text="что думаешь про это решение?")
            is AnswerDemand.HIGH
        )

    def test_explain_request_is_high(self) -> None:
        assert (
            classify_answer_demand(text="расскажи про свой день")
            is AnswerDemand.HIGH
        )

    def test_compare_request_is_high(self) -> None:
        assert (
            classify_answer_demand(text="сравни эти два подхода")
            is AnswerDemand.HIGH
        )

    def test_english_what_do_you_think_is_high(self) -> None:
        assert (
            classify_answer_demand(text="what do you think about this?")
            is AnswerDemand.HIGH
        )

    def test_english_explain_is_high(self) -> None:
        assert (
            classify_answer_demand(text="explain how it works please")
            is AnswerDemand.HIGH
        )

    def test_multipart_question_is_high(self) -> None:
        # Несколько вопросов в одной реплике — много-частный запрос.
        assert (
            classify_answer_demand(text="успел? и как настроение?")
            is AnswerDemand.HIGH
        )


class TestClassifyAnswerDemandMedium:
    """MEDIUM — всё прочее, включая пустой/None-вход (без падений)."""

    def test_plain_statement_is_medium(self) -> None:
        assert (
            classify_answer_demand(text="сегодня был обычный рабочий день")
            is AnswerDemand.MEDIUM
        )

    def test_none_is_medium(self) -> None:
        assert classify_answer_demand(text=None) is AnswerDemand.MEDIUM

    def test_empty_is_medium(self) -> None:
        assert classify_answer_demand(text="   ") is AnswerDemand.MEDIUM


# --- decide_verbosity: база --------------------------------------------------

_NEUTRAL_MOOD = 0.0
_LOW_INTEREST = 0.0
_GOOD_ENGAGEMENT = 1.0
_NO_UPGRADE_ROLL = 0.99  # выше любой малой частоты апгрейда → апгрейда нет


class TestVerbosityBase:
    """База: demand задаёт ступень при нейтральных интересе/настроении."""

    def test_low_demand_maps_to_terse(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_medium_demand_maps_to_normal(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.MEDIUM,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.NORMAL

    def test_high_demand_maps_to_expansive(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.EXPANSIVE


# --- decide_verbosity: интерес↑ (US-4) ---------------------------------------


class TestVerbosityInterestUpgrade:
    """Высокий интерес изредка (seeded) поднимает ступень — не выше EXPANSIVE."""

    def test_high_interest_lucky_roll_upgrades_terse_to_normal(self) -> None:
        thresholds = BrevityThresholds()
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=1.0,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=0.0,  # ниже малой частоты апгрейда → срабатывает
            is_owner=False,
            thresholds=thresholds,
        )
        assert result is Verbosity.NORMAL

    def test_high_interest_unlucky_roll_does_not_upgrade(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=1.0,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,  # выше частоты → апгрейда нет
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_modest_interest_lucky_roll_does_not_upgrade(self) -> None:
        # Интерес ниже высокого порога — даже удачный roll не апгрейдит.
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=0.5,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=0.0,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_interest_upgrade_caps_at_expansive(self) -> None:
        # Уже EXPANSIVE: апгрейд не выходит за потолок.
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=1.0,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=0.0,
            is_owner=False,
        )
        assert result is Verbosity.EXPANSIVE


# --- decide_verbosity: настроение/аппетит↓ (US-3) ----------------------------

_BAD_MOOD = -0.8
_LOW_ENGAGEMENT = 0.1


class TestVerbosityDownshift:
    """Плохое настроение / низкий аппетит детерминированно урезают ступень."""

    def test_bad_mood_downshifts_expansive_to_normal(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.NORMAL

    def test_bad_mood_downshifts_normal_to_terse(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.MEDIUM,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_low_engagement_downshifts(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.MEDIUM,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_LOW_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_downshift_clips_at_terse(self) -> None:
        # Уже TERSE: даун-шифт не уходит ниже потолка снизу.
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_LOW_ENGAGEMENT,
            form_hint=FormHint.TERSE,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE


# --- decide_verbosity: form_hint-наклон (BOB-018) ----------------------------


class TestVerbosityFormHintTilt:
    """form_hint — мягкий вход: усиливает наклон настроения, но не перебивает базу."""

    def test_terse_form_hint_reinforces_downshift(self) -> None:
        # form_hint TERSE толкает вниз вместе с плохим настроением → даун-шифт.
        result = decide_verbosity(
            demand=AnswerDemand.MEDIUM,
            interest=_LOW_INTEREST,
            mood_valence=-0.4,  # мягко плохое, само по себе не урезает
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.TERSE,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_form_hint_does_not_override_demand_base(self) -> None:
        # TERSE-хинт при нейтральном настроении НЕ опускает HIGH ниже базы один-в-один:
        # база demand остаётся основой, хинт сам по себе её не перебивает.
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.TERSE,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.EXPANSIVE

    def test_normal_form_hint_is_neutral(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.MEDIUM,
            interest=_LOW_INTEREST,
            mood_valence=_NEUTRAL_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.NORMAL


# --- decide_verbosity: анти-обрубок owner (US-5) -----------------------------


class TestVerbosityAntiCurtOwner:
    """HIGH-demand owner не опускается ниже NORMAL, что бы ни было с настроением."""

    def test_high_demand_owner_stays_at_least_normal_in_bad_mood(self) -> None:
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_LOW_ENGAGEMENT,
            form_hint=FormHint.TERSE,
            roll=_NO_UPGRADE_ROLL,
            is_owner=True,
        )
        assert result is Verbosity.NORMAL

    def test_high_demand_non_owner_can_drop_below_normal(self) -> None:
        # Тот же вход, но не owner — даун-шифт пробивает ниже NORMAL.
        result = decide_verbosity(
            demand=AnswerDemand.HIGH,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_LOW_ENGAGEMENT,
            form_hint=FormHint.TERSE,
            roll=_NO_UPGRADE_ROLL,
            is_owner=False,
        )
        assert result is Verbosity.TERSE

    def test_low_demand_owner_is_not_floored(self) -> None:
        # Анти-обрубок только для HIGH-demand: простой вопрос owner остаётся TERSE.
        result = decide_verbosity(
            demand=AnswerDemand.LOW,
            interest=_LOW_INTEREST,
            mood_valence=_BAD_MOOD,
            engagement=_GOOD_ENGAGEMENT,
            form_hint=FormHint.NORMAL,
            roll=_NO_UPGRADE_ROLL,
            is_owner=True,
        )
        assert result is Verbosity.TERSE


# --- BrevityThresholds -------------------------------------------------------


class TestBrevityThresholds:
    """Пороги — иммутабельны, дефолты консервативны, валидируются."""

    def test_defaults_are_conservative(self) -> None:
        thresholds = BrevityThresholds()
        assert thresholds.interest_upgrade >= 0.8
        assert thresholds.upgrade_freq <= 0.2

    def test_is_frozen(self) -> None:
        thresholds = BrevityThresholds()
        with pytest.raises((AttributeError, TypeError)):
            thresholds.upgrade_freq = 0.5  # type: ignore[misc]

    def test_rejects_out_of_range_frequency(self) -> None:
        with pytest.raises(ValueError, match="upgrade_freq"):
            BrevityThresholds(upgrade_freq=1.5)
