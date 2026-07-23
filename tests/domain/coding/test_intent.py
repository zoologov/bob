# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure approve/stop predicates (BOB-041 .2 → BOB-042 .4).

The predicates classify ONE short owner reply by CONTENT (BOB-042 .4): an affirmative
token ("ок", "да", "давай"…) approves the waiting plan, a stop/negation token ("стоп",
"отмена", "не надо"…) kills the session. Conservatism is part of safety — a long
off-topic message that merely mentions an approval word, a negated reply, or a fresh
task must NOT auto-approve (default to chat on doubt). Stop is checked FIRST, so a
message carrying both a stop and an affirmative is a stop, never an approve. Matching
is word-boundary aware (after normalisation) so "да" inside "создай" never bites.
"""

from __future__ import annotations

import pytest

from bob.coding.intent import is_approval, is_stop


@pytest.mark.parametrize(
    "text",
    [
        # BOB-042 .4 — natural approvals (content, not exact whole-message match).
        "План, ок, давай",
        "да, поехали",
        "ок",
        "да",
        "давай, погнали",
        "утверждаю, давай",
        # BOB-041 .2 — original whole-phrase approvals still match.
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
        # BOB-042 .4 — stop/negation replies never read as approval.
        "отмена, не надо",
        "не сейчас",
        "нет",
        # A long off-topic message that merely contains "ок" must NOT auto-approve.
        "ок, а можешь ещё сделать вот это большое другое потом",
        # Word boundary: "да" inside "создай" is not an affirmative token.
        "создай файл hello.md",
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
        # BOB-042 .4 — content stop + stop-first ordering.
        "не надо, отмена",
        "не надо, стоп",
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


def test_stop_first_a_message_with_both_a_stop_and_an_affirmative_is_a_stop() -> None:
    # "не надо, стоп" carries a stop token AND no affirmative — stop wins, never approve.
    assert is_stop("не надо, стоп") is True
    assert is_approval("не надо, стоп") is False
