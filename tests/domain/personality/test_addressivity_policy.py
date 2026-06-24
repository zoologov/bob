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
