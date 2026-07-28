# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты NL-предикатов решения owner — grant/deny/authorize (BOB-052 .1).

Чистые, детерминированные, консервативные (как BOB-042 ``is_approval``/``is_stop``):
совпадение по границам слов, отрицание ветирует grant, длинный абзац → не команда,
любая неоднозначность → ``False``. Эти предикаты вычисляются ТОЛЬКО для owner (в .2).
"""

from __future__ import annotations

import pytest

from bob.social.permission.intent import is_authorize, is_deny, is_grant


@pytest.mark.parametrize(
    "text",
    ["да", "разреши", "покажи", "ок", "Да, покажи", "разрешаю", "можно"],
)
def test_is_grant_true_on_clear_affirmatives(text: str) -> None:
    assert is_grant(text) is True


@pytest.mark.parametrize(
    "text",
    ["нет", "откажи", "не надо", "не разрешаю", "нельзя", "Нет, не показывай"],
)
def test_is_grant_false_when_denied_or_negated(text: str) -> None:
    assert is_grant(text) is False


def test_is_grant_word_boundary_no_false_positive() -> None:
    # «создай» contains «да» as a substring — must not grant.
    assert is_grant("создай отчёт") is False


def test_is_grant_false_on_long_paragraph() -> None:
    assert is_grant("ну да наверное но вообще давай попозже когда будет время потом") is False


@pytest.mark.parametrize(
    "text",
    ["нет", "откажи", "не надо", "не показывай", "нельзя", "отказать"],
)
def test_is_deny_true_on_clear_refusals(text: str) -> None:
    assert is_deny(text) is True


@pytest.mark.parametrize("text", ["да", "разреши", "покажи", "ок", "конечно"])
def test_is_deny_false_on_affirmatives(text: str) -> None:
    assert is_deny(text) is False


def test_grant_and_deny_are_mutually_exclusive_on_clear_inputs() -> None:
    assert is_grant("да") is True
    assert is_deny("да") is False
    assert is_deny("нет") is True
    assert is_grant("нет") is False


@pytest.mark.parametrize(
    "text",
    ["авторизуй Нормана", "авторизуй его", "добавь в список", "дай доступ Норману"],
)
def test_is_authorize_true_on_durable_phrasing(text: str) -> None:
    assert is_authorize(text) is True


@pytest.mark.parametrize("text", ["да", "покажи", "разреши", "нет", "ок"])
def test_is_authorize_false_on_plain_grant_or_deny(text: str) -> None:
    # A one-off grant is NOT a durable authorize.
    assert is_authorize(text) is False


def test_ambiguous_empty_is_false_everywhere() -> None:
    assert is_grant("") is False
    assert is_deny("") is False
    assert is_authorize("") is False
