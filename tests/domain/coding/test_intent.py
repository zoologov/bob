# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure approve/stop predicates (BOB-041 .2).

Conservative phrase matching: a clear approval/stop short phrase matches, while a
question or an unrelated chat message NEVER does (default to chat on doubt — a
false-positive could approve a coding session, so the predicates must not bite on
an ambiguous message that merely contains an approval-ish word).
"""

from __future__ import annotations

import pytest

from bob.domain.coding.intent import is_approval, is_stop


@pytest.mark.parametrize(
    "text",
    [
        "давай",
        "го",
        "апрув",
        "поехали",
        "погнали",
        "ок делай",
        "окей, делай",
        "да, делай",
        "approve",
        "одобряю",
        "  Давай!  ",
    ],
)
def test_approval_phrases_match(text: str) -> None:
    assert is_approval(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "а давай попозже, сначала расскажи про тесты",
        "не надо",
        "что там по плану?",
        "расскажи подробнее про космос",
        "",
        "стоп",  # a stop is not an approval
        "почему именно так делаешь?",
    ],
)
def test_non_approval_messages_do_not_match(text: str) -> None:
    assert is_approval(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "стоп",
        "отмена",
        "останови",
        "отмени",
        "stop",
        "хватит",
        "  Стоп.  ",
    ],
)
def test_stop_phrases_match(text: str) -> None:
    assert is_stop(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "не останавливайся, продолжай",
        "давай",
        "расскажи про остановку поездов",
        "",
        "а что если остановить на полпути?",
    ],
)
def test_non_stop_messages_do_not_match(text: str) -> None:
    assert is_stop(text) is False
