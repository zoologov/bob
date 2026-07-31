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


class TestGenderReadAccumulation:
    def test_fresh_read_is_unknown(self) -> None:
        assert GenderRead().resolve() is Gender.UNKNOWN

    def test_one_clean_feminine_message_resolves_fem(self) -> None:
        read = GenderRead().observe("Пошла учить Python")
        assert read.resolve() is Gender.FEM

    def test_one_clean_masculine_message_resolves_masc(self) -> None:
        read = GenderRead().observe("я сделал ревью")
        assert read.resolve() is Gender.MASC

    def test_third_person_quote_does_not_move_the_read(self) -> None:
        # A lone 3rd-person/quoted gendered verb must not force a gender.
        read = GenderRead().observe("пошёл он в магазин")
        assert read.resolve() is Gender.UNKNOWN

    def test_neutral_message_keeps_prior_read(self) -> None:
        read = GenderRead().observe("Пошла учить Python").observe("окей, спасибо")
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
