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
    is_phrase_tic,
    is_user_repeat,
    recalled_bob_replies,
    recalled_bob_reply,
    recalled_excluding_reflections,
    recalled_without_copied_exemplars,
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


def test_repeat_thresholds_tic_defaults_are_conservative() -> None:
    # BOB-036 .1: the phrase-tic knobs default to a closer-sized phrase (>=3 words)
    # recurring at least twice — so a short closer or a one-off never trips.
    thresholds = RepeatThresholds()
    assert thresholds.tic_min_words >= 3
    assert thresholds.tic_min_occurrences >= 2


def test_repeat_thresholds_rejects_tic_min_words_below_one() -> None:
    with pytest.raises(ValueError, match="tic_min_words"):
        RepeatThresholds(tic_min_words=0)


def test_repeat_thresholds_rejects_tic_min_occurrences_below_one() -> None:
    with pytest.raises(ValueError, match="tic_min_occurrences"):
        RepeatThresholds(tic_min_occurrences=0)


# --- Phrase-tic detector (BOB-036 .1) -----------------------------------------
#
# BOB-032 anti-repeat compares FULL replies (threshold 0.9), so two substantively
# DIFFERENT messages that merely share a signature CLOSER ("Мне так спокойнее.")
# slip through. is_phrase_tic is the phrase-level guard: a notable phrase of the
# candidate (>= min_words words) that ALSO recurs as a notable phrase across
# >= min_occurrences recent replies is a tic. Pure, deterministic, no I/O.

_TIC = "Мне так спокойнее."


def test_recurring_closer_across_two_replies_is_a_tic() -> None:
    # The signature closer ends >= 2 recent replies; a fresh candidate ending with
    # it (different lead-in) is a tic.
    recent = [
        f"Хорошо, посмотрю логи. {_TIC}",
        f"Ладно, перепишу функцию. {_TIC}",
    ]
    candidate = f"Окей, проверю конфиг. {_TIC}"
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is True


def test_closer_appearing_only_once_before_is_not_a_tic() -> None:
    # A phrase that recurs only ONCE in the window is not yet a tic (min_occurrences=2).
    recent = [
        f"Хорошо, посмотрю логи. {_TIC}",
        "Совсем другой ответ без закрывашки.",
    ]
    candidate = f"Окей, проверю конфиг. {_TIC}"
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_short_common_closer_below_min_words_is_not_a_tic() -> None:
    # "Работаем." is a single word — below min_words=3 — so even recurring it never trips.
    recent = ["Сделаю. Работаем.", "Понял. Работаем."]
    candidate = "Ок, гляну. Работаем."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_substantively_different_reply_with_no_shared_phrase_does_not_fire() -> None:
    # No shared notable phrase across the window -> no false fire.
    recent = [
        "Давай разберём архитектуру по слоям.",
        "Я бы начал с доменной модели.",
    ]
    candidate = "Предлагаю сначала написать тест."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_one_off_long_phrase_reused_once_is_not_a_tic() -> None:
    # A long phrase the candidate shares with exactly ONE recent reply is a legitimate
    # reuse, not a tic.
    shared = "Это решает задачу синхронизации индекса."
    recent = [shared, "Совсем другая мысль про космос."]
    candidate = f"Кстати: {shared}"
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_tic_is_case_and_whitespace_insensitive() -> None:
    # Notable phrases are normalised (strip / casefold / collapse ws) before compare.
    recent = [
        "Лог посмотрю.   МНЕ  ТАК   спокойнее.",
        "Код перепишу. мне так спокойнее.",
    ]
    candidate = "Конфиг гляну.  Мне Так Спокойнее."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is True


def test_tic_matches_a_mid_reply_sentence_not_only_the_final_one() -> None:
    # Any sentence >= min_words counts as notable, not only the closer.
    phrase = "это меня успокаивает совершенно"
    recent = [
        f"{phrase}. А дальше посмотрим.",
        f"Ну ладно. {phrase}. Идём дальше.",
    ]
    candidate = f"{phrase}. И что теперь."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is True


def test_blank_candidate_is_never_a_tic() -> None:
    assert is_phrase_tic("", [_TIC, _TIC], min_words=3, min_occurrences=2) is False


def test_empty_recent_window_is_never_a_tic() -> None:
    candidate = f"Окей, проверю конфиг. {_TIC}"
    assert is_phrase_tic(candidate, [], min_words=3, min_occurrences=2) is False


def test_same_phrase_twice_in_one_reply_counts_as_one_occurrence() -> None:
    # A phrase repeated WITHIN a single recent reply is still that ONE reply — it must
    # not inflate the occurrence count past min_occurrences on its own.
    recent = [f"{_TIC} И ещё раз. {_TIC}"]
    candidate = f"Окей. {_TIC}"
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


# --- Recall-aware anti-repeat helpers (BOB-032 .1, shared domain logic) --------
#
# A recalled episode is stored as a whole turn "<sender>: <text>\nbob: <old reply>"
# (same shape as history; see HandleMessage._persist). These pure helpers recover
# Bob's "bob:" half so the reactive AND proactive guards can compare a fresh
# candidate against his OWN recalled past replies — and drop the copied exemplar on
# the retry — without either path duplicating the predicate.

_OLD_REPLY = "Звучит как угроза."
_EPISODE: dict[str, object] = {"content": f"Ada: ты опять?\nbob: {_OLD_REPLY}"}
_FACT: dict[str, object] = {"content": "Ada предпочитает чай"}


def test_recalled_bob_reply_recovers_the_bob_half() -> None:
    # The single-item extractor returns exactly the bob: half (the copyable exemplar).
    assert recalled_bob_reply(_EPISODE) == _OLD_REPLY


def test_recalled_bob_reply_fact_only_memory_yields_blank() -> None:
    # A fact-only memory has no "\nbob: " marker -> no copyable exemplar.
    assert recalled_bob_reply(_FACT) == ""


def test_recalled_bob_reply_non_string_content_yields_blank() -> None:
    # A non-string content (e.g. structured metadata) is not a turn -> blank.
    assert recalled_bob_reply({"content": 123}) == ""
    assert recalled_bob_reply({}) == ""


def test_recalled_bob_reply_uses_the_last_marker_for_multiline_user_text() -> None:
    # rfind on the marker: a user half that itself mentions "bob:" must not split early
    # — only the FINAL "\nbob: " starts Bob's reply.
    item = {"content": "Ada: помнишь bob: что-то?\nbob: Да, помню."}
    assert recalled_bob_reply(item) == "Да, помню."


def test_recalled_bob_replies_recovers_all_and_skips_facts_and_blanks() -> None:
    # The plural form gathers every real bob: exemplar, dropping fact-only, blank, and
    # non-string memories — only copyable reply exemplars feed the guard.
    recalled: list[dict[str, object]] = [
        _FACT,
        {"content": "Ada: пусто\nbob: "},  # blank bob: half
        {"content": 999},  # non-string
        _EPISODE,
    ]
    assert recalled_bob_replies(recalled) == (_OLD_REPLY,)


def test_recalled_bob_replies_empty_is_empty_tuple() -> None:
    assert recalled_bob_replies([]) == ()


def test_recalled_without_copied_exemplars_drops_only_the_matched_episode() -> None:
    # R2: a candidate copying _OLD_REPLY drops exactly that episode; the fact-only
    # memory (grounding) is preserved untouched — facts are never weakened.
    kept = recalled_without_copied_exemplars(
        _OLD_REPLY, [_EPISODE, _FACT], threshold=0.9
    )
    assert kept == (_FACT,)


def test_recalled_without_copied_exemplars_keeps_all_when_no_match() -> None:
    # A substantively different candidate matches no exemplar -> nothing is dropped.
    kept = recalled_without_copied_exemplars(
        "Свежая мысль про космос, ничего общего.", [_EPISODE, _FACT], threshold=0.9
    )
    assert kept == (_EPISODE, _FACT)


def test_recalled_without_copied_exemplars_drops_every_matching_exemplar() -> None:
    # When two recalled episodes carry the SAME copied reply, BOTH are dropped (the
    # attractor is fully withheld), while an unrelated episode survives.
    dup = {"content": f"Bo: эхо\nbob: {_OLD_REPLY}"}
    other = {"content": "Cy: привет\nbob: Совсем другое."}
    kept = recalled_without_copied_exemplars(
        _OLD_REPLY, [_EPISODE, dup, other, _FACT], threshold=0.9
    )
    assert kept == (other, _FACT)


def test_recalled_without_copied_exemplars_empty_input_is_empty() -> None:
    assert recalled_without_copied_exemplars("что угодно", [], threshold=0.9) == ()


# --- Reflection containment for the reply-recall pool (BOB-033 .3) -------------
#
# Bob's private reflections (inner monologue) must NOT become copyable exemplars in
# user-facing replies: the inner life colours tone via MOOD, not by the model
# parroting reflection TEXT. The recall pool that feeds compose excludes episodes
# whose ``category`` (= the episodic ``event_type``) is a reflection kind, while
# facts and past message turns still ground the reply.

_REFLECTION: dict[str, object] = {
    "content": "Сегодня тянет на меланхолию.",
    "category": "reflection",
    "source": "episodic",
}
_INNER_MONOLOGUE: dict[str, object] = {
    "content": "Что-то я заскучал.",
    "category": "inner_monologue",
    "source": "episodic",
}
_MESSAGE_TURN: dict[str, object] = {
    "content": "Ada: привет\nbob: Привет!",
    "category": "message",
    "source": "episodic",
}
_SEMANTIC_FACT: dict[str, object] = {
    "content": "Ada любит чай",
    "category": "preference",
    "source": "semantic",
}


def test_reflection_episodes_are_excluded_from_the_reply_pool() -> None:
    # A reflection in the store is NEVER returned as a compose exemplar.
    kept = recalled_excluding_reflections(
        [_REFLECTION, _INNER_MONOLOGUE, _MESSAGE_TURN, _SEMANTIC_FACT]
    )
    assert _REFLECTION not in kept
    assert _INNER_MONOLOGUE not in kept


def test_messages_and_facts_are_still_recalled() -> None:
    # Containment is surgical: facts and past message turns still feed the reply.
    kept = recalled_excluding_reflections(
        [_REFLECTION, _MESSAGE_TURN, _SEMANTIC_FACT]
    )
    assert kept == (_MESSAGE_TURN, _SEMANTIC_FACT)


def test_excluding_reflections_preserves_order_and_passes_through_non_reflections() -> None:
    assert recalled_excluding_reflections([_MESSAGE_TURN, _SEMANTIC_FACT]) == (
        _MESSAGE_TURN,
        _SEMANTIC_FACT,
    )


def test_excluding_reflections_is_case_insensitive_on_category() -> None:
    upper = {"content": "x", "category": "REFLECTION", "source": "episodic"}
    assert recalled_excluding_reflections([upper]) == ()


def test_excluding_reflections_empty_is_empty() -> None:
    assert recalled_excluding_reflections([]) == ()


def test_excluding_reflections_keeps_memory_with_no_category() -> None:
    # A memory without a category key is not a reflection -> kept (defensive default).
    no_cat: dict[str, object] = {"content": "что-то"}
    assert recalled_excluding_reflections([no_cat]) == (no_cat,)
