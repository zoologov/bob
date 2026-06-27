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
    recurring_closer,
    strip_recurring_closer,
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


def test_repeat_thresholds_rejects_tic_lookback_below_one() -> None:
    # BOB-043: the WIDE closer-lookback window must be >= 1 — a non-positive
    # lookback would read no closers and silently disable the scattered-tic catch.
    with pytest.raises(ValueError, match="tic_lookback"):
        RepeatThresholds(tic_lookback=0)


def test_repeat_thresholds_tic_lookback_default_is_wide() -> None:
    # BOB-043: the default lookback is WIDE (>> the narrow ~6 history window) so a
    # ~21%-prevalence scattered tic recurs enough times to clear min_occurrences.
    thresholds = RepeatThresholds()
    assert thresholds.tic_lookback >= 20  # pins the wide default (>> narrow ~6)


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


def test_users_real_case_signature_closer_across_two_replies_is_a_tic() -> None:
    # 🔴 The user's actual report: "Мне так спокойнее" closes >= 2 recent Bob replies,
    # and a fresh, otherwise-different draft ending with it is the tic to catch. This is
    # the exact production phrase (3 words), not a synthetic one.
    recent = [
        "Развернул сервис, всё поднялось. Мне так спокойнее.",
        "Прогнал тесты ещё раз перед сном. Мне так спокойнее.",
    ]
    candidate = "Сделал бэкап на всякий случай. Мне так спокойнее."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is True


def test_reused_proper_noun_is_not_a_tic_below_min_words() -> None:
    # No false fire on legitimately reused proper nouns / short technical terms: a name
    # like "Telegram" or "Ollama" is a single token, far below min_words=3, so even when
    # it recurs every reply it is never a notable phrase and never trips the detector.
    recent = [
        "Подключаюсь к Ollama.",
        "Снова дёргаю Ollama для ответа.",
    ]
    candidate = "Отправляю это в Ollama."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_short_technical_term_reused_is_not_a_tic() -> None:
    # A short technical term ("FTS5 индекс" — 2 words) recurring across replies is a
    # legitimate domain phrase below the 3-word notability bar, not a tic.
    recent = [
        "Перестрою FTS5 индекс.",
        "Снова трогаю FTS5 индекс.",
    ]
    candidate = "Чищу FTS5 индекс."
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


def test_tic_fires_only_at_the_min_occurrences_boundary() -> None:
    # Off-by-one at the threshold: the SAME notable phrase recurs in exactly two replies.
    # With min_occurrences=3 that is below the bar (not a tic); with min_occurrences=2 it
    # is exactly at the bar (a tic). Pins min_occurrences as a real, inclusive cutoff.
    recent = [
        f"Глянул дашборд. {_TIC}",
        f"Перечитал лог. {_TIC}",
    ]
    candidate = f"Проверил алерты. {_TIC}"
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=3) is False
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is True


def test_blank_recent_replies_contribute_no_occurrence() -> None:
    # A blank / whitespace recent reply yields no notable phrases, so it can never count
    # toward the occurrence tally — only real shared phrases do.
    recent = ["", "   ", f"Лог посмотрю. {_TIC}"]
    candidate = f"Конфиг гляну. {_TIC}"
    # Only one real occurrence -> below min_occurrences=2 -> not a tic.
    assert is_phrase_tic(candidate, recent, min_words=3, min_occurrences=2) is False


# --- BOB-043: wide-lookback recurring closer + deterministic strip --------------
#
# The narrow per-turn window (6-episode history + query-recall) sees a SCATTERED tic
# (~21% prevalence) only 0–1× -> below min_occurrences. Over a WIDE window (~20 of
# Bob's closers) it recurs ~4× -> reliably caught. ``recurring_closer`` returns the
# candidate's FINAL notable phrase iff it recurs across that window; the pure
# ``strip_recurring_closer`` then removes exactly that trailing tic sentence so the
# tic never ships even if regeneration can't shake it.


def test_recurring_closer_returns_the_final_phrase_when_it_recurs() -> None:
    # The candidate's FINAL notable phrase recurs in >= min_occurrences of the wide
    # window -> it is the recurring closer (returned normalised).
    candidate = f"Сделал бэкап на всякий случай. {_TIC}"
    window = [
        f"Развернул сервис. {_TIC}",
        f"Прогнал тесты. {_TIC}",
    ]
    assert (
        recurring_closer(candidate, window, min_words=3, min_occurrences=2)
        == "мне так спокойнее"
    )


def test_recurring_closer_catches_a_scattered_tic_in_a_wide_window() -> None:
    # The headline case: the tic appears in only 4 of the last 20 replies (21%
    # prevalence). A narrow 6-window would see it 0–1× (below the bar); the wide
    # window sees 4 occurrences -> caught.
    scattered = [f"Реплика {i}." for i in range(20)]
    for index in (3, 8, 12, 17):
        scattered[index] = f"Что-то сделал. {_TIC}"
    candidate = f"Свежий повод. {_TIC}"
    assert (
        recurring_closer(candidate, scattered, min_words=3, min_occurrences=2)
        == "мне так спокойнее"
    )


def test_recurring_closer_one_off_ending_is_not_a_recurrence() -> None:
    # A DISTINCT, non-recurring closer (appears in only one prior reply) is below
    # min_occurrences -> not a recurring closer -> None (no false positive strip).
    candidate = "Готово. Это разовая концовка такая."
    window = [
        "Что-то сделал. Это разовая концовка такая.",
        f"Другое сделал. {_TIC}",
    ]
    assert recurring_closer(candidate, window, min_words=3, min_occurrences=2) is None


def test_recurring_closer_short_final_phrase_below_min_words_is_ignored() -> None:
    # A short/common closer below min_words ("Работаем" — 1 word) is never notable,
    # so it can never be a recurring closer even when it recurs every reply.
    candidate = "Поправил конфиг. Работаем."
    window = ["А. Работаем.", "Б. Работаем."]
    assert recurring_closer(candidate, window, min_words=3, min_occurrences=2) is None


def test_strip_recurring_closer_removes_the_trailing_tic_sentence() -> None:
    text = f"Готово, бэкап на месте. {_TIC}"
    assert strip_recurring_closer(text, "мне так спокойнее") == "Готово, бэкап на месте."


def test_strip_recurring_closer_leaves_a_distinct_ending_intact() -> None:
    # When the passed closer is NOT the trailing sentence, nothing is stripped.
    text = "Готово, бэкап на месте. Совсем другая концовка тут."
    assert strip_recurring_closer(text, "мне так спокойнее") == text


def test_strip_recurring_closer_blank_closer_is_a_noop() -> None:
    text = f"Готово. {_TIC}"
    assert strip_recurring_closer(text, "   ") == text


def test_strip_recurring_closer_tidies_trailing_whitespace() -> None:
    text = f"Готово, всё чисто.   {_TIC}   "
    assert strip_recurring_closer(text, "мне так спокойнее") == "Готово, всё чисто."


# --- BOB-043 .2: recurring_closer / strip_recurring_closer guardrails ----------
#
# Edge + no-false-positive cases for the deterministic-strip helpers. The strip is
# the LAST line of defence (fires only after regeneration cannot shake the tic), so
# it must (a) only ever fire on a closer that genuinely RECURS across the wide window,
# and (b) excise EXACTLY the trailing tic sentence — never mangle the substantive body
# or a legitimate earlier reuse of the same phrase.


def test_recurring_closer_empty_window_is_not_a_recurrence() -> None:
    # An empty wide window (e.g. Bob's first replies, or a guest turn) -> nothing to
    # recur against -> None, so the strip fallback never fires with no evidence.
    candidate = f"Сделал бэкап на всякий случай. {_TIC}"
    assert recurring_closer(candidate, [], min_words=3, min_occurrences=2) is None


def test_recurring_closer_blank_candidate_is_not_a_recurrence() -> None:
    # A blank candidate has no final notable phrase -> None (never strips nothing).
    window = [f"Развернул сервис. {_TIC}", f"Прогнал тесты. {_TIC}"]
    assert recurring_closer("   ", window, min_words=3, min_occurrences=2) is None


def test_recurring_closer_uses_final_notable_phrase_skipping_a_short_tail() -> None:
    # The CLOSER is the last NOTABLE sentence: a trailing short fragment ("Ок.", 1
    # word) after the real closer is skipped, so the recurring tic is still detected.
    candidate = f"Сделал бэкап на всякий случай. {_TIC} Ок."
    window = [f"Развернул сервис. {_TIC}", f"Прогнал тесты. {_TIC}"]
    assert (
        recurring_closer(candidate, window, min_words=3, min_occurrences=2)
        == "мне так спокойнее"
    )


def test_recurring_closer_exactly_at_min_occurrences_boundary() -> None:
    # Off-by-one at the recurrence boundary: a closer in EXACTLY min_occurrences (2)
    # replies recurs; one in only (min_occurrences - 1) does not.
    candidate = f"Свежий повод. {_TIC}"
    two = [f"Развернул сервис. {_TIC}", f"Прогнал тесты. {_TIC}"]
    one = [f"Развернул сервис. {_TIC}", "Прогнал тесты. Идём дальше работать."]
    assert recurring_closer(candidate, two, min_words=3, min_occurrences=2) is not None
    assert recurring_closer(candidate, one, min_words=3, min_occurrences=2) is None


def test_strip_recurring_closer_removes_only_the_final_occurrence() -> None:
    # No-mangle guardrail: when the closer phrase ALSO appears earlier (a legitimate
    # mid-reply reuse), only the TRAILING occurrence is excised — the earlier sentence
    # and the substantive body in between are left intact.
    text = f"{_TIC} И ещё сделал бэкап подробно. {_TIC}"
    assert (
        strip_recurring_closer(text, "мне так спокойнее")
        == "Мне так спокойнее. И ещё сделал бэкап подробно."
    )


def test_strip_recurring_closer_drops_a_short_fragment_trailing_the_closer() -> None:
    # The closer plus any trailing short tail after it is tidied away in one go, the
    # substantive body surviving untouched.
    text = f"Готово, всё чисто. {_TIC} Ок."
    assert strip_recurring_closer(text, "мне так спокойнее") == "Готово, всё чисто."


def test_strip_recurring_closer_preserves_a_multi_sentence_body() -> None:
    # The substantive reply can be several sentences: only the trailing tic sentence
    # is removed; every body sentence (and its punctuation) survives intact.
    text = f"Первая часть готова. Вторая часть тоже готова. {_TIC}"
    assert (
        strip_recurring_closer(text, "мне так спокойнее")
        == "Первая часть готова. Вторая часть тоже готова."
    )


def test_recurring_closer_and_strip_are_pure_and_deterministic() -> None:
    # The helpers are pure: identical inputs -> identical outputs across calls, and the
    # caller's window list is never mutated (no I/O, no hidden state).
    candidate = f"Сделал бэкап на всякий случай. {_TIC}"
    window = [f"Развернул сервис. {_TIC}", f"Прогнал тесты. {_TIC}"]
    window_snapshot = list(window)

    first = recurring_closer(candidate, window, min_words=3, min_occurrences=2)
    second = recurring_closer(candidate, window, min_words=3, min_occurrences=2)

    assert first == second == "мне так спокойнее"
    assert window == window_snapshot
    assert strip_recurring_closer(candidate, first or "") == strip_recurring_closer(
        candidate, first or ""
    )


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
