# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the self-identification gender detector + accumulation (BOB-078 A).

Bob must address a person in the right grammatical gender — derived ONLY from how
they present themselves in their own speech (1st-person gendered past-tense verbs /
explicit «я сам»/«я сама»), NEVER from their name. A gendered verb about a THIRD
person or in a quote must not decide, and a weak/absent signal stays UNKNOWN
(neutral — Bob forces nothing). The contract pinned here is the pure detector and
the confidence accumulator; both are I/O-free and deterministic.
"""

from __future__ import annotations

from bob.social.gender import Gender, GenderRead, detect_self_gender


class TestDetectSelfGender:
    def test_feminine_self_verb_reads_fem(self) -> None:
        assert detect_self_gender("Пошла учить Python") is Gender.FEM

    def test_feminine_reflexive_self_verb_reads_fem(self) -> None:
        assert detect_self_gender("Я разобралась с багом") is Gender.FEM

    def test_masculine_self_verb_after_ya_reads_masc(self) -> None:
        assert detect_self_gender("я сделал") is Gender.MASC

    def test_explicit_ya_sama_marker_reads_fem(self) -> None:
        assert detect_self_gender("Я сама справлюсь, спасибо") is Gender.FEM

    def test_explicit_ya_sam_marker_reads_masc(self) -> None:
        assert detect_self_gender("да я сам всё починю") is Gender.MASC

    def test_third_person_gendered_verb_is_not_self(self) -> None:
        # «пошёл он …» — the verb belongs to «он» (3rd person), not the speaker.
        assert detect_self_gender("пошёл он в магазин") is Gender.UNKNOWN

    def test_gendered_verb_about_she_is_not_self(self) -> None:
        assert detect_self_gender("она сделала всё сама") is Gender.UNKNOWN

    def test_neutral_text_reads_unknown(self) -> None:
        assert detect_self_gender("Какая сегодня погода в Москве?") is Gender.UNKNOWN

    def test_name_alone_reads_unknown_no_grammar(self) -> None:
        # 🔴 Never infer gender from a name — «Лиля» carries no self-presentation verb.
        assert detect_self_gender("Лиля") is Gender.UNKNOWN

    def test_name_introduction_reads_unknown(self) -> None:
        assert detect_self_gender("Меня зовут Лиля, пишу фронт") is Gender.UNKNOWN

    def test_empty_text_reads_unknown(self) -> None:
        assert detect_self_gender("") is Gender.UNKNOWN

    def test_mixed_fem_and_masc_self_verbs_read_unknown(self) -> None:
        # Contradictory self-signals in one message → do not decide.
        assert detect_self_gender("я сделал, а потом я устала") is Gender.UNKNOWN

    def test_gendered_verb_handed_to_trailing_subject_is_not_self(self) -> None:
        # «сделала она» — the verb belongs to the trailing «она», even at message end.
        assert detect_self_gender("сделала она") is Gender.UNKNOWN

    def test_short_four_letter_feminine_verb_still_reads_fem(self) -> None:
        # «была» (4 letters) is a real feminine past-tense verb — the length floor keeps it.
        assert detect_self_gender("Я была права") is Gender.FEM

    def test_masculine_reflexive_verb_reads_masc(self) -> None:
        assert detect_self_gender("я разобрался с этим сам") is Gender.MASC

    def test_short_four_letter_masculine_verb_reads_masc(self) -> None:
        assert detect_self_gender("я спал весь день") is Gender.MASC

    def test_masculine_verb_with_consonant_stem_reads_masc(self) -> None:
        # «пошёл»: the vowel that qualifies the «-л» is the one BEFORE it («ё»),
        # not the third character («ш»).
        assert detect_self_gender("я пошёл домой") is Gender.MASC

    def test_third_person_masc_subject_before_verb_is_not_self(self) -> None:
        # 🔴 PRD A (живой инвариант): «он пошёл …» — подлежащее «он» СТОИТ ПЕРЕД глаголом,
        # поэтому глагол вообще не в self-позиции (i>0, слева не «я») → детектор молчит и НЕ
        # приписывает собеседнику мужской род ошибочно. Это ДРУГОЙ путь, чем «пошёл он»
        # (там глагол в позиции 0, но передан trailing-подлежащему): здесь режет _is_self_position.
        assert detect_self_gender("он пошёл в магазин за хлебом") is Gender.UNKNOWN

    def test_third_person_fem_subject_before_verb_is_not_self(self) -> None:
        # Женский двойник: «она пошла …» — глагол принадлежит «она», не говорящему → UNKNOWN.
        assert detect_self_gender("она пошла домой уставшая") is Gender.UNKNOWN

    def test_second_person_subject_before_gendered_verb_is_not_self(self) -> None:
        # 🔴 «ты сделал …» / «ты пошла …» — родовой глагол ПОСЛЕ «ты» (2-е лицо) — это про
        # СОБЕСЕДНИКА, не про говорящего: слева не «я» → не self-позиция → UNKNOWN. Так пол
        # говорящего не выводится из формы, адресованной адресату.
        assert detect_self_gender("ты сделал это зря") is Gender.UNKNOWN
        assert detect_self_gender("ты пошла не туда") is Gender.UNKNOWN

    def test_masc_verb_handed_to_trailing_second_person_subject_is_not_self(self) -> None:
        # «сделал ты» — глагол в позиции 0, но вплотную за ним 2-е лицо «ты» (а не «я») →
        # передан trailing-подлежащему → не self-сигнал (guard шире, чем только «он»/«она»).
        assert detect_self_gender("сделал ты") is Gender.UNKNOWN

    def test_feminine_verb_opening_a_mid_message_sentence_is_not_read_standalone(self) -> None:
        # 🔴 ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ (найдено живым смоуком, BOB-078 A): родовой глагол,
        # открывающий ВТОРОЕ предложение сообщения («Привет, Боб. Пролистала чат…»), НЕ
        # читается сам по себе — self-позиция это начало ВСЕГО сообщения или сразу после «я»,
        # а границы предложения детектор не видит (пунктуация срезается токенайзером). Живая
        # реплика Лили в изоляции даёт UNKNOWN; продакшн восстанавливает род накоплением по
        # её другим репликам (см. TestGenderReadAccumulation ниже). Тест ПИНит это поведение,
        # чтобы регресс/фикс были заметны.
        assert (
            detect_self_gender("Привет, Боб. Пролистала чат, тут много интересного")
            is Gender.UNKNOWN
        )


class TestGenderReadAccumulation:
    def test_fresh_read_is_unknown(self) -> None:
        assert GenderRead().resolve() is Gender.UNKNOWN

    def test_one_clean_feminine_message_only_leans_not_commits(self) -> None:
        # 🔴 BOB-078.8: ОДИН само-сигнал только НАКЛОНЯЕТ (lean), но НЕ коммитит род —
        # наружу всё ещё UNKNOWN. Так ведущий родовой глагол в одном сообщении не
        # переворачивает пол за один ход (инвариант PRD).
        read = GenderRead().observe("Пошла учить Python")
        assert read.resolve() is Gender.UNKNOWN

    def test_two_clean_feminine_messages_commit_fem(self) -> None:
        # Второй согласный само-сигнал добирает порог → коммит FEM.
        read = GenderRead().observe("Пошла учить Python").observe("Я разобралась с багом")
        assert read.resolve() is Gender.FEM

    def test_one_clean_masculine_message_only_leans_not_commits(self) -> None:
        read = GenderRead().observe("я сделал ревью")
        assert read.resolve() is Gender.UNKNOWN

    def test_two_clean_masculine_messages_commit_masc(self) -> None:
        read = GenderRead().observe("я сделал ревью").observe("я разобрался сам")
        assert read.resolve() is Gender.MASC

    def test_leading_verb_with_noun_subject_does_not_commit(self) -> None:
        # 🔴 BOB-078.8 (ядро фикса): сообщение, НАЧИНАЮЩЕЕся с родового глагола при
        # подлежащем-существительном («Была ошибка в коде», «Сделана миграция»), даёт лишь
        # lean — за ОДИН ход род НЕ коммитится (ложный FEM недопустим). Только повторный
        # согласный сигнал добрал бы порог.
        read = GenderRead().observe("Была ошибка в коде")
        assert read.resolve() is Gender.UNKNOWN

    def test_third_person_quote_does_not_move_the_read(self) -> None:
        # A lone 3rd-person/quoted gendered verb must not force a gender.
        read = GenderRead().observe("пошёл он в магазин")
        assert read.resolve() is Gender.UNKNOWN

    def test_neutral_message_keeps_prior_committed_read(self) -> None:
        # Два согласных сигнала коммитят FEM; последующая нейтральная реплика не сбивает.
        read = (
            GenderRead()
            .observe("Пошла учить Python")
            .observe("Я разобралась с багом")
            .observe("окей, спасибо")
        )
        assert read.resolve() is Gender.FEM

    def test_conflicting_signals_net_back_to_unknown(self) -> None:
        read = GenderRead().observe("Пошла гулять").observe("я сделал")
        assert read.resolve() is Gender.UNKNOWN

    def test_repeated_feminine_signal_stays_fem_and_bounded(self) -> None:
        read = GenderRead()
        for _ in range(5):
            read = read.observe("Пролистала чат")
        assert read.resolve() is Gender.FEM
        assert -1.0 <= read.lean <= 1.0

    def test_lily_real_session_accumulates_to_fem(self) -> None:
        # 🔴 Живой кейс Лили целиком (мотив эпика): её реальная сессия — приветствие с
        # родовым глаголом во втором предложении (сам по себе не читается), комплимент «Ты
        # классный!» (нейтрален по роду) и ДВЕ чистые само-презентации («Пошла учить Python»,
        # «Я разобралась с багом»). По СУММЕ ходов накопленный род (≥2 согласных сигнала,
        # BOB-078.8) resolve'ится в FEM — Боб обращается к ней в женском роде, хотя ни имя,
        # ни отдельная приветственная строка этого не дали.
        read = GenderRead()
        for line in (
            "Привет, Боб. Пролистала чат, тут много интересного",
            "Ты классный!",
            "Пошла учить Python",
            "Я разобралась с багом",
        ):
            read = read.observe(line)
        assert read.resolve() is Gender.FEM

    def test_neutral_only_session_stays_unknown(self) -> None:
        # Сессия без единого само-презентационного сигнала (нейтральные реплики) → накопления
        # нет, род остаётся UNKNOWN → Боб обращается нейтрально (ничего не форсирует).
        read = GenderRead()
        for line in ("какая погода", "спасибо", "интересно, а что дальше"):
            read = read.observe(line)
        assert read.resolve() is Gender.UNKNOWN
