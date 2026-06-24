# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the user-repeat detection predicate (BOB-022).

A pure, conservative predicate: does the OWNER's current message exactly repeat
(after normalisation) something they already said in the recent window? It is
deliberately EXACT-after-normalise (strip / casefold / collapse internal
whitespace), never fuzzy, so it can never false-fire on a merely-similar turn.
"""

from __future__ import annotations

import pytest

from bob.domain.personality.conversation import (
    RepeatThresholds,
    is_bob_repeat,
    is_user_repeat,
)


def test_exact_repeat_of_a_recent_user_turn_is_a_repeat() -> None:
    assert is_user_repeat("как ты?", ["привет", "как ты?"]) is True


def test_a_different_message_is_not_a_repeat() -> None:
    assert is_user_repeat("чем занят?", ["привет", "как ты?"]) is False


def test_case_variation_is_still_a_repeat() -> None:
    assert is_user_repeat("КАК ТЫ?", ["как ты?"]) is True


def test_surrounding_and_internal_whitespace_is_normalised() -> None:
    assert is_user_repeat("  как   ты?  ", ["как ты?"]) is True


def test_empty_current_text_is_never_a_repeat() -> None:
    assert is_user_repeat("", ["", "  "]) is False


def test_no_prior_user_turns_is_not_a_repeat() -> None:
    assert is_user_repeat("как ты?", []) is False


def test_matches_any_prior_user_turn_in_the_window_not_just_the_last() -> None:
    assert is_user_repeat("первый", ["первый", "второй", "третий"]) is True


# --- Bob-repeat near-duplicate detection (BOB-026 .1, окно анти-повтора) -------


def test_bob_verbatim_repeat_is_caught() -> None:
    """Дословный повтор после нормализации ловится."""
    assert is_bob_repeat("Нет, таблицу я не нарисую.", ["Нет, таблицу я не нарисую."]) is True


def test_bob_repeat_through_a_turn_is_caught_anywhere_in_the_window() -> None:
    """Повтор «через ход» — кандидат совпадает не с последним, а с более ранним ответом."""
    recent = ["серое какое-то настроение", "Нет, таблицу я не нарисую."]
    assert is_bob_repeat("Нет, таблицу я не нарисую.", recent) is True


def test_bob_case_and_whitespace_variation_is_still_a_repeat() -> None:
    assert (
        is_bob_repeat("  НЕТ,   таблицу я не нарисую.  ", ["нет, таблицу я не нарисую."])
        is True
    )


def test_bob_near_verbatim_minor_edit_is_caught() -> None:
    """Near-verbatim: мелкая правка одной фразы из длинного ответа — повтор."""
    prior = (
        "Извини, рисовать таблицы я пока не умею — это вне моих возможностей, "
        "но могу описать данные словами, если хочешь."
    )
    candidate = (
        "Извини, рисовать таблицы я пока не умею — это вне моих возможностей, "
        "но могу описать данные словами, если захочешь."
    )
    assert is_bob_repeat(candidate, [prior]) is True


def test_bob_genuinely_different_reply_is_not_a_repeat() -> None:
    """Анти-ложно-срабатывание: разные по сути ответы НЕ ловятся."""
    prior = "Нет, таблицу я не нарисую — это вне моих возможностей."
    candidate = "Конечно, давай разберёмся с задачей вместе. С чего начнём?"
    assert is_bob_repeat(candidate, [prior]) is False


def test_bob_similar_topic_different_answer_is_not_a_repeat() -> None:
    """Похожая тема, но другой ответ — не повтор (консервативный порог)."""
    prior = "Сегодня настроение серое, тянет помолчать."
    candidate = "Сегодня я бодрый, готов хоть горы свернуть и поболтать обо всём."
    assert is_bob_repeat(candidate, [prior]) is False


def test_bob_empty_candidate_is_never_a_repeat() -> None:
    assert is_bob_repeat("", ["что-то", "  "]) is False


def test_bob_no_recent_replies_is_not_a_repeat() -> None:
    assert is_bob_repeat("любой ответ", []) is False


def test_bob_blank_recent_replies_are_skipped() -> None:
    assert is_bob_repeat("реальный ответ", ["", "   "]) is False


def test_custom_threshold_is_honoured() -> None:
    """С низким порогом даже умеренно похожие ответы считаются повтором."""
    prior = "Сегодня настроение серое, тянет помолчать немного."
    candidate = "Сегодня настроение серое, хочется помолчать немного."
    assert is_bob_repeat(candidate, [prior], threshold=0.5) is True


# --- RepeatThresholds config dataclass (BOB-026 .1) ---------------------------


def test_repeat_thresholds_defaults_are_conservative() -> None:
    thresholds = RepeatThresholds()
    assert thresholds.window >= 1
    assert 0.0 <= thresholds.similarity_threshold <= 1.0


def test_repeat_thresholds_rejects_window_below_one() -> None:
    with pytest.raises(ValueError, match="window"):
        RepeatThresholds(window=0)


def test_repeat_thresholds_rejects_out_of_range_threshold() -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        RepeatThresholds(similarity_threshold=1.5)
