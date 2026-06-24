# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the addressivity response policy (BOB-023).

:func:`decide_response` отображает адресность + интерес + seeded-роль на исход
(ENGAGE / REACT / SILENT): к Бобу → всегда ENGAGE; к другому → SILENT, интерес
изредка втягивает (высокий порог); ambient в 1:1 → ENGAGE, ambient с другими →
SILENT/REACT, изредка втягивает легче.
"""

from __future__ import annotations

from bob.domain.personality.addressivity import (
    Addressivity,
    AddressivityThresholds,
    ResponseOutcome,
    decide_response,
)

_T = AddressivityThresholds()


def _decide(
    addressivity: Addressivity,
    *,
    interest: float,
    others_present: bool,
    roll: float,
    thresholds: AddressivityThresholds = _T,
) -> ResponseOutcome:
    return decide_response(
        addressivity,
        interest=interest,
        others_present=others_present,
        roll=roll,
        thresholds=thresholds,
    )


# --- DIRECTED_TO_BOB: всегда ENGAGE, никогда SILENT --------------------------


def test_directed_to_bob_always_engages_even_with_no_interest() -> None:
    out = _decide(
        Addressivity.DIRECTED_TO_BOB, interest=0.0, others_present=True, roll=0.99
    )
    assert out is ResponseOutcome.ENGAGE


def test_directed_to_bob_engages_even_with_boring_topic_in_one_to_one() -> None:
    out = _decide(
        Addressivity.DIRECTED_TO_BOB, interest=0.0, others_present=False, roll=0.99
    )
    assert out is ResponseOutcome.ENGAGE


# --- DIRECTED_TO_OTHER: по умолчанию SILENT, интерес изредка втягивает --------


def test_directed_to_other_is_silent_by_default() -> None:
    out = _decide(
        Addressivity.DIRECTED_TO_OTHER, interest=0.0, others_present=True, roll=0.0
    )
    assert out is ResponseOutcome.SILENT


def test_directed_to_other_high_interest_low_roll_barges_in() -> None:
    # Сильный интерес + удачный (редкий) seeded-роль → изредка вклинивается.
    out = _decide(
        Addressivity.DIRECTED_TO_OTHER, interest=1.0, others_present=True, roll=0.0
    )
    assert out is ResponseOutcome.ENGAGE


def test_directed_to_other_high_interest_high_roll_stays_silent() -> None:
    # Интерес есть, но роль не выпал (частота мала) → молчит, не перехватывает.
    out = _decide(
        Addressivity.DIRECTED_TO_OTHER, interest=1.0, others_present=True, roll=0.99
    )
    assert out is ResponseOutcome.SILENT


def test_directed_to_other_threshold_is_higher_than_ambient() -> None:
    # Порог интереса для вклинивания в чужой 1:1 ВЫШЕ, чем для ambient.
    assert _T.barge_in_interest > _T.ambient_interest


# --- AMBIENT в 1:1 с owner: вступает -----------------------------------------


def test_ambient_one_to_one_engages() -> None:
    out = _decide(
        Addressivity.AMBIENT, interest=0.0, others_present=False, roll=0.99
    )
    assert out is ResponseOutcome.ENGAGE


# --- AMBIENT с другими: SILENT/REACT, изредка втягивает легче -----------------


def test_ambient_with_others_default_reacts_or_silent() -> None:
    out = _decide(
        Addressivity.AMBIENT, interest=0.0, others_present=True, roll=0.99
    )
    assert out in (ResponseOutcome.SILENT, ResponseOutcome.REACT)


def test_ambient_with_others_high_interest_low_roll_engages() -> None:
    out = _decide(
        Addressivity.AMBIENT, interest=1.0, others_present=True, roll=0.0
    )
    assert out is ResponseOutcome.ENGAGE


def test_ambient_with_others_engages_easier_than_directed_to_other() -> None:
    # При одинаковом высоком интересе ambient втягивает на большей частоте, чем
    # вклинивание в чужой диалог (легче присоединиться к общему).
    assert _T.ambient_barge_in_freq >= _T.barge_in_freq


# --- Guardrail-инвариант: DIRECTED_TO_BOB НИКОГДА не SILENT (свип) ------------


def test_directed_to_bob_never_silent_across_interest_roll_and_company() -> None:
    # Перебор по интересу x роли x наличию других: прямое обращение к Бобу всегда
    # ENGAGE и никогда SILENT/REACT — инвариант пользователя «к Бобу → всегда ответ».
    for interest in (0.0, 0.3, 0.6, 1.0):
        for roll in (0.0, 0.2, 0.5, 0.8, 0.999):
            for others in (True, False):
                out = _decide(
                    Addressivity.DIRECTED_TO_BOB,
                    interest=interest,
                    others_present=others,
                    roll=roll,
                )
                assert out is ResponseOutcome.ENGAGE, (interest, roll, others)


# --- Guardrail-инвариант: AMBIENT в 1:1 ВСЕГДА вступает (свип) ----------------


def test_ambient_one_to_one_always_engages_across_interest_and_roll() -> None:
    # В личном 1:1 (нет других) ambient — пространство Боба: всегда ENGAGE, при любом
    # интересе и любой роли. Боб не уходит в вечное молчание в своём пространстве.
    for interest in (0.0, 0.5, 1.0):
        for roll in (0.0, 0.5, 0.999):
            out = _decide(
                Addressivity.AMBIENT,
                interest=interest,
                others_present=False,
                roll=roll,
            )
            assert out is ResponseOutcome.ENGAGE, (interest, roll)


# --- Guardrail: вклинивание в чужой диалог РЕДКО (свип на дефолтных порогах) ---


def test_directed_to_other_barge_in_is_rare_on_default_thresholds() -> None:
    # На дефолтных (консервативных) порогах вклинивание в чужой 1:1 редко даже при
    # максимальном интересе: подавляющее большинство роллов → SILENT, ENGAGE — лишь
    # на узкой полосе roll < barge_in_freq. Боб не перехватывает чужой разговор.
    engages = sum(
        _decide(
            Addressivity.DIRECTED_TO_OTHER,
            interest=1.0,
            others_present=True,
            roll=roll,
        )
        is ResponseOutcome.ENGAGE
        for roll in (i / 100 for i in range(100))
    )
    # Полоса вклинивания == barge_in_freq (0.05) → не больше ~5 из 100.
    assert engages <= 5
    assert engages >= 1  # но возможность изредка вклиниться всё же есть


def test_directed_to_other_never_engages_below_interest_threshold() -> None:
    # Ниже высокого порога интереса вклинивания не происходит даже при удачном ролле:
    # только сильно интересная тема может втянуть.
    out = _decide(
        Addressivity.DIRECTED_TO_OTHER,
        interest=_T.barge_in_interest - 0.01,
        others_present=True,
        roll=0.0,
    )
    assert out is ResponseOutcome.SILENT


def test_ambient_with_others_react_band_sits_between_engage_and_silent() -> None:
    # Полоса REACT (лайк присутствия) лежит между полосой вступления и молчанием:
    # роль в [ambient_barge_in_freq, ambient_barge_in_freq + react_chance) при низком
    # интересе → REACT, выше → SILENT.
    react_roll = _T.ambient_barge_in_freq + _T.react_chance / 2
    silent_roll = min(0.999, _T.ambient_barge_in_freq + _T.react_chance + 0.01)
    assert (
        _decide(
            Addressivity.AMBIENT, interest=0.0, others_present=True, roll=react_roll
        )
        is ResponseOutcome.REACT
    )
    assert (
        _decide(
            Addressivity.AMBIENT, interest=0.0, others_present=True, roll=silent_roll
        )
        is ResponseOutcome.SILENT
    )


def test_decide_response_uses_default_thresholds_when_none_passed() -> None:
    # thresholds=None → берутся дефолтные пороги (та же ветка, что и явный _T).
    out = decide_response(
        Addressivity.DIRECTED_TO_OTHER,
        interest=1.0,
        others_present=True,
        roll=0.999,
        thresholds=None,
    )
    assert out is ResponseOutcome.SILENT
