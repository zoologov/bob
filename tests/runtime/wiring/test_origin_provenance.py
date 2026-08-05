# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Флаг ``memory.origin_provenance`` — выключатель провенанса «где это было» (BOB-090.C1).

Одно место, где читается голый флаг (по образцу ``memory.work_journal`` /
``memory.register_recall``): OFF (дефолт) → :class:`VoiceComposer` не вплетает пометку об
источнике, и системный промпт байт-в-байт прежний. ON → Боб видит, где был сказан
припомненный эпизод, и перестаёт домысливать место.

🔴 Пропущенная секция, пустая секция и явный ``false`` — все OFF: случайно уехавший ключ
не должен незаметно менять голос Боба.
"""

from __future__ import annotations

from bob.runtime.wiring.parameters import _build_origin_provenance


def test_missing_section_is_off() -> None:
    assert _build_origin_provenance({}) is False


def test_empty_section_is_off() -> None:
    assert _build_origin_provenance({"memory": {}}) is False


def test_explicit_false_is_off() -> None:
    assert _build_origin_provenance({"memory": {"origin_provenance": False}}) is False


def test_explicit_true_is_on() -> None:
    assert _build_origin_provenance({"memory": {"origin_provenance": True}}) is True


def test_env_string_boolean_is_tolerated() -> None:
    # Флаги приезжают и из окружения (BOB_MEMORY__ORIGIN_PROVENANCE="true").
    assert _build_origin_provenance({"memory": {"origin_provenance": "true"}}) is True
    assert _build_origin_provenance({"memory": {"origin_provenance": "false"}}) is False


def test_a_neighbouring_memory_flag_does_not_switch_it_on() -> None:
    # Ось «где сказано» ортогональна оси регистра «про что» (BOB-087.C): включённый
    # register_recall не включает провенанс, и наоборот.
    assert _build_origin_provenance({"memory": {"register_recall": True}}) is False
