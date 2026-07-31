# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the persona voice directives (BOB-016).

Two persona/voice concerns pinned here as pure helpers, mirroring
``language.py``: the *anti-bait* directive + few-shot that breaks Qwen's RLHF
"end on an engagement-bait question + ☕ signature" tic, and the *GUPPI canon*
that fixes GUPPI's gender (male, "он") and seeds Bob's wry running relationship
with his non-sentient executor. The contract is structural — presence of the
voice guidance, the substance-ending exemplars, and the male-gendered GUPPI
flavor — never a brittle full-string match (the prose is free to evolve).
"""

from __future__ import annotations

import pytest

from bob.personality.expression import EngagementLevel, Verbosity
from bob.personality.mood import Mood
from bob.personality.voice import (
    OffDayThresholds,
    RelationshipToneThresholds,
    anti_bait_directive,
    brevity_directive,
    brevity_few_shot,
    disclosure_refusal_directive,
    engagement_directive,
    guppi_canon,
    improvement_directive,
    profanity_stance,
    recalled_impression_directive,
    relationship_tone_directive,
    stranger_directive,
    sulk_directive,
    tactful_withhold_directive,
    tone_directive,
    user_repeat_directive,
    variable_form_directive,
    who_is_writing_directive,
)
from bob.social.gender import Gender
from bob.social.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)


def test_improvement_directive_empty_when_no_adjustments() -> None:
    # Нет TONE/HUMOR-поправок → нет директивы (поведение как до BOB-028).
    assert improvement_directive(()) == ""


def test_improvement_directive_folds_grounded_adjustments() -> None:
    text = improvement_directive(("говорить теплее", "чуть больше иронии"))
    assert text != ""
    # Директива грундирована в реальных поправках (не выдумана).
    assert "говорить теплее" in text
    assert "чуть больше иронии" in text


def test_anti_bait_directive_is_natural_voice_not_a_rule_list() -> None:
    directive = anti_bait_directive()
    folded = directive.casefold()
    # It guides HOW Bob ends a thought (no fishing for continuation) as voice,
    # and it never reads like a numbered/bulleted rule list Bob could recite.
    assert "вопрос" in folded  # talks about when (not) to ask a question
    assert "•" not in directive
    assert "- " not in directive


def test_anti_bait_directive_addresses_the_emoji_signature_tic() -> None:
    # The ☕ "sign every message" reflex is named so the model drops it.
    folded = anti_bait_directive().casefold()
    assert "эмодзи" in folded or "emoji" in folded


def test_anti_bait_directive_carries_substance_ending_exemplars() -> None:
    # The few-shot is what actually breaks the tic: at least one short exemplar
    # Bob line that ENDS ON SUBSTANCE — no trailing question, no ☕ signature.
    directive = anti_bait_directive()
    assert "☕" not in directive  # the exemplars must not model the signature
    # An exemplar line exists and does not end on a question mark.
    exemplars = _exemplar_lines(directive)
    assert exemplars, "no few-shot exemplar lines found"
    assert all(not line.rstrip().endswith("?") for line in exemplars)


def test_guppi_canon_establishes_male_gender() -> None:
    # GUPPI is "он": Bob must refer to him in the masculine, never "она"/"её".
    canon = guppi_canon()
    tokens = {t.strip(".,:;«»()—-") for t in canon.casefold().split()}
    assert "он" in tokens  # the masculine pronoun is present as its own word
    # No feminine agreement for GUPPI leaks into the canon.
    assert "она" not in tokens
    assert "её" not in tokens


def test_guppi_canon_names_him_as_bobs_non_sentient_executor() -> None:
    # The relationship flavor: GUPPI is Bob's literal, non-sentient executor
    # subsystem — the seed for the running gags.
    folded = guppi_canon().casefold()
    assert "guppi" in folded
    assert "исполн" in folded  # executes / executor
    assert "разум" in folded  # (non-)sentient


def test_guppi_canon_seeds_running_relationship_flavor() -> None:
    # Bob's wry relationship is seeded (literal-to-a-fault, glad he isn't
    # sentient — "fewer philosophical arguments") so it can surface naturally.
    folded = guppi_canon().casefold()
    assert "буквальн" in folded or "дословн" in folded
    assert "кофе" in folded  # the "philosophical arguments over coffee" gag seed


def test_variable_form_directive_is_natural_voice_not_a_rule_list() -> None:
    # The variable-form directive (BOB-018) is written as voice — Bob's form and
    # length vary by mood, not one fixed frame — never a recitable rule list.
    directive = variable_form_directive()
    folded = directive.casefold()
    assert "форма" in folded  # speaks about the shape/form of his replies
    assert "•" not in directive
    assert "- " not in directive


def test_variable_form_directive_names_the_one_frame_tic() -> None:
    # It names the failure it counters: every reply in one shape/length (a rut),
    # so sometimes short, sometimes expansive.
    folded = variable_form_directive().casefold()
    assert "коротк" in folded  # sometimes terse
    assert "развёрнут" in folded or "развернут" in folded  # sometimes expansive


def test_variable_form_directive_carries_a_few_shot() -> None:
    # A short few-shot (between « ») shows the varied form, mirroring anti-bait.
    exemplars = _exemplar_lines(variable_form_directive())
    assert exemplars, "no few-shot exemplar lines found"


# --- BOB-061: the recurring meme closer must NOT be re-seeded by the exemplars ---
# The verbal tic Bob kept emitting was SEEDED verbatim by the static voice exemplars
# injected into the reply prompt every turn: the paired signature closer «пусть
# остаётся как есть» + «мне так спокойнее» (and the «оставить как есть» variant) lived
# inside the anti-bait and variable-form few-shots, so Bob mimicked them. The root-cause
# fix rewords the exemplars to keep their pedagogy while removing the tic seed; these
# guards keep the closer out so it can never be re-planted in the exemplars.
_MEME_CLOSER_FRAGMENTS = (
    "пусть остаётся как есть",
    "мне так спокойнее",
    "оставить как есть",
    "остаётся как есть",
)


def test_anti_bait_exemplars_do_not_seed_the_meme_closer() -> None:
    folded = anti_bait_directive().casefold()
    for fragment in _MEME_CLOSER_FRAGMENTS:
        assert fragment not in folded, f"anti-bait re-seeds the tic closer: {fragment!r}"


def test_variable_form_exemplars_do_not_seed_the_meme_closer() -> None:
    folded = variable_form_directive().casefold()
    for fragment in _MEME_CLOSER_FRAGMENTS:
        assert fragment not in folded, f"variable-form re-seeds the closer: {fragment!r}"


def test_no_voice_directive_pairs_the_signature_closer() -> None:
    # The specific tic is the PAIRED signature — «пусть остаётся как есть» AND «мне так
    # спокойнее» closing together. No injected voice directive may carry both.
    for accessor in (anti_bait_directive, variable_form_directive, guppi_canon):
        folded = accessor().casefold()
        assert not (
            "пусть остаётся как есть" in folded and "мне так спокойнее" in folded
        )


@pytest.mark.parametrize(
    "accessor", [anti_bait_directive, variable_form_directive, guppi_canon]
)
def test_no_injected_voice_directive_seeds_the_meme_closer(accessor: object) -> None:
    # 🔴 US-1/.7 HARDEN: the seed guard covers EVERY statically-injected voice directive —
    # including guppi_canon, whose «тихо спокойнее» phrasing was reworded in .7. No accessor
    # may re-plant any fragment of the paired meme signature.
    folded = accessor().casefold()  # type: ignore[operator]
    for fragment in _MEME_CLOSER_FRAGMENTS:
        assert fragment not in folded, f"{accessor} re-seeds the tic closer: {fragment!r}"


def test_guppi_canon_no_longer_uses_the_spokoynee_phrasing() -> None:
    # 🔴 .7 root-cause detail: guppi_canon's old «тебе тихо спокойнее» fed the «спокойнее»
    # half of the tic. The reword («ты тихо рад») must leave no «спокойнее» in the canon.
    assert "спокойнее" not in guppi_canon().casefold()


def test_no_voice_directive_carries_the_leave_as_is_variant() -> None:
    # The «оставить как есть» / «остаётся как есть» variant is gone from BOTH few-shots that
    # once modelled it (anti-bait AND variable-form), so it can never be mimicked back.
    for accessor in (anti_bait_directive, variable_form_directive):
        folded = accessor().casefold()
        assert "оставить как есть" not in folded
        assert "остаётся как есть" not in folded


def test_anti_bait_still_teaches_its_point_after_the_reword() -> None:
    # The reword is surgical: anti-bait STILL teaches "end on substance, don't fish for
    # continuation" and still carries a substance-ending exemplar (no trailing question).
    folded = anti_bait_directive().casefold()
    assert "не выпрашивай продолжение" in folded
    exemplars = _exemplar_lines(anti_bait_directive())
    assert exemplars
    assert all(not e.rstrip().endswith("?") for e in exemplars)


def test_variable_form_still_teaches_variety_after_the_reword() -> None:
    # Variety pedagogy intact: still speaks about terse vs expansive form, and its
    # few-shot shows the SAME thought both ways (>= 2 exemplars).
    folded = variable_form_directive().casefold()
    assert "коротк" in folded
    assert "развёрнут" in folded or "развернут" in folded
    assert len(_exemplar_lines(variable_form_directive())) >= 2


def test_tone_directive_normal_mood_is_warm_and_concise() -> None:
    # A neutral/good mood keeps Bob's current warm, concise base tone (BOB-020):
    # tone_directive replaces the old unconditional "warmly and concisely" line,
    # so on a normal day it must still read as warm.
    directive = tone_directive(Mood(valence=0.3, arousal=0.2))
    folded = directive.casefold()
    assert "тепл" in folded  # warm
    assert "не в ресурсе" not in folded  # not the off-day band


def test_tone_directive_off_day_is_vulnerable_and_honest_not_warm_forced() -> None:
    # Low valence AND low energy (below the off-day threshold) → Bob may be quieter,
    # more restrained, vulnerable; an honest "не знаю" beats confabulating warmth.
    directive = tone_directive(Mood(valence=-0.6, arousal=-0.5))
    folded = directive.casefold()
    assert "не в ресурсе" in folded  # off-day band: not at full resource
    assert "не знаю" in folded  # honest "I don't know" over forcing an answer
    assert "уязвим" in folded or "тише" in folded  # vulnerable / quieter


def test_tone_directive_off_day_is_not_rude() -> None:
    # Off-day is quieter/honest, NOT a relational sulk (that is BOB-014). The
    # directive must not license rudeness/hostility.
    folded = tone_directive(Mood(valence=-0.7, arousal=-0.6)).casefold()
    # It explicitly disavows rudeness/sulking rather than licensing it.
    assert "не груб" in folded or "без груб" in folded  # explicitly: not rude
    assert "обида" in folded  # names off-day != BOB-014 relational sulk
    # No hostile/aggressive licensing leaks in.
    assert "агресс" not in folded
    assert "огрызай" not in folded


def test_relationship_tone_warm_for_a_close_relationship() -> None:
    # BOB-014: a high-warmth relationship colours Bob's voice warmer/closer.
    directive = relationship_tone_directive(0.8)
    folded = directive.casefold()
    assert "тепл" in folded or "близ" in folded  # warmer / closer


def test_relationship_tone_cooler_for_a_distant_relationship() -> None:
    # A low-warmth relationship reads cooler/more reserved — but NOT rude/hostile
    # (relational hostility is the sulk, BOB-014 .2, not this).
    directive = relationship_tone_directive(-0.8)
    folded = directive.casefold()
    assert "суш" in folded or "сдержан" in folded or "прохлад" in folded  # cooler
    # Never rude here (relational hostility is the sulk, .2): the cool band reads as
    # reserved and EXPLICITLY disavows rudeness rather than licensing it.
    assert "не груб" in folded or "без груб" in folded  # disavows, never licenses
    assert "агресс" not in folded
    assert "огрызай" not in folded


def test_relationship_tone_neutral_band_adds_no_directive() -> None:
    # A neutral (mid-band) relationship adds no extra colour — the base voice/tone
    # already covers it, so the default path is unchanged.
    assert relationship_tone_directive(0.0) == ""


def test_relationship_tone_thresholds_come_from_config() -> None:
    # The warm/cool bands are configurable, so the boundary is not hardcoded.
    mood = 0.2
    strict = RelationshipToneThresholds(warm=0.9, cool=-0.9)
    lenient = RelationshipToneThresholds(warm=0.1, cool=-0.1)
    assert relationship_tone_directive(mood, thresholds=strict) == ""
    assert relationship_tone_directive(mood, thresholds=lenient) != ""


def test_relationship_tone_is_voice_not_a_rule_list() -> None:
    directive = relationship_tone_directive(0.9)
    assert "•" not in directive
    assert "- " not in directive


def test_tone_directive_is_voice_not_a_rule_list() -> None:
    # Written as character voice (like anti_bait/variable_form), never a recitable
    # bullet/numbered list.
    directive = tone_directive(Mood(valence=-0.6, arousal=-0.5))
    assert "•" not in directive
    assert "- " not in directive


def test_tone_directive_threshold_comes_from_config() -> None:
    # The off-day threshold(s) are configurable: a strict threshold leaves a mildly
    # low mood on the warm tone, while a lenient one trips the off-day band for the
    # same mood — so the boundary is config-driven, not hardcoded.
    mood = Mood(valence=-0.2, arousal=-0.15)
    strict = OffDayThresholds(valence=-0.9, arousal=-0.9)
    lenient = OffDayThresholds(valence=-0.1, arousal=-0.1)
    assert "не в ресурсе" not in tone_directive(mood, thresholds=strict).casefold()
    assert "не в ресурсе" in tone_directive(mood, thresholds=lenient).casefold()


def test_off_day_thresholds_defaults_are_negative_low_band() -> None:
    # Sensible defaults (Q4): the off-day band sits in the low/negative region of
    # the axes, so a normal or good mood never trips it.
    defaults = OffDayThresholds()
    assert defaults.valence < 0.0
    assert defaults.arousal < 0.0


def test_user_repeat_directive_tells_bob_to_notice_the_repeat() -> None:
    # BOB-022: when the owner repeats himself, Bob notices it in character — he
    # never pretends he did not, and never silently re-answers the same way.
    folded = user_repeat_directive().casefold()
    assert "повтор" in folded  # it names that the interlocutor is repeating


def test_user_repeat_directive_forbids_pretending_and_re_answering() -> None:
    # The two anti-patterns this fix targets are named: don't act as if you did
    # not notice, and don't just hand back the same answer again.
    folded = user_repeat_directive().casefold()
    assert "не делай вид" in folded
    assert "тот же" in folded


def test_user_repeat_directive_is_voice_not_a_rule_list() -> None:
    # Character guidance, not a recitable checklist (mirrors the other directives).
    directive = user_repeat_directive()
    assert "•" not in directive
    assert "- " not in directive


def test_who_is_writing_directive_names_the_owner_by_name_as_owner() -> None:
    # BOB-019: Bob perceives WHO is writing and recognises the owner AS the owner,
    # by name, folded into the prompt as character — not as a config flag.
    who = Interlocutor(
        sender_id=1,
        display_name="Vova",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "vova" in folded  # the name reaches the prompt
    assert "владел" in folded  # recognised as the owner (владелец)


def test_who_is_writing_directive_names_a_known_friend() -> None:
    who = Interlocutor(
        sender_id=2,
        display_name="Ada",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "ada" in folded
    assert "знаком" in folded  # a known person (знакомый)


def test_who_is_writing_directive_marks_a_stranger() -> None:
    who = Interlocutor(
        sender_id=3,
        display_name="Stranger",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "stranger" in folded
    assert "незнаком" in folded  # a stranger (незнакомец)


def test_who_is_writing_directive_marks_a_bot() -> None:
    who = Interlocutor(
        sender_id=4,
        display_name="PeerBot",
        kind=InterlocutorKind.BOT,
        trust=Trust.GUEST,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "peerbot" in folded
    assert "бот" in folded


def test_who_is_writing_directive_addresses_a_feminine_interlocutor_in_fem() -> None:
    # BOB-078 A: gender read from self-presentation folds into how Bob addresses her.
    who = Interlocutor(
        sender_id=5,
        display_name="Лиля",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
        gender=Gender.FEM,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "женск" in folded  # обращайся в женском роде


def test_who_is_writing_directive_addresses_a_masculine_interlocutor_in_masc() -> None:
    who = Interlocutor(
        sender_id=6,
        display_name="Паша",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
        gender=Gender.MASC,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "мужск" in folded  # обращайся в мужском роде


def test_who_is_writing_directive_forces_no_gender_when_unknown() -> None:
    # 🔴 UNKNOWN → neutral: Bob forces neither gender (no name-based guessing).
    who = Interlocutor(
        sender_id=7,
        display_name="Саша",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
        gender=Gender.UNKNOWN,
    )
    folded = who_is_writing_directive(who).casefold()
    assert "женск" not in folded
    assert "мужск" not in folded


def test_who_is_writing_directive_is_voice_not_a_rule_list() -> None:
    who = Interlocutor(
        sender_id=1,
        display_name="Vova",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )
    directive = who_is_writing_directive(who)
    assert "•" not in directive
    assert "- " not in directive


def test_stranger_directive_is_a_wary_but_human_greeting() -> None:
    # BOB-019 bob-apv.2: the guest (restricted) turn appends this — Bob meets a
    # stranger as a person (greet / stay wary / politely decline / suggest asking
    # the owner), in character, never a config flag.
    folded = stranger_directive().casefold()
    assert "незнаком" in folded  # he is meeting a stranger
    # it covers the human options Bob can take with a stranger
    assert "владел" in folded  # may suggest asking the owner


def test_stranger_directive_forbids_revealing_owner_private_info() -> None:
    # The security character line: Bob must NOT spill the owner's private info to
    # a guest. This is voice mirroring the application-level redaction invariant.
    folded = stranger_directive().casefold()
    assert "личн" in folded or "приват" in folded  # do not reveal owner's private stuff


def test_stranger_directive_is_voice_not_a_rule_list() -> None:
    directive = stranger_directive()
    assert "•" not in directive
    assert "- " not in directive


def test_tactful_withhold_directive_points_to_the_owner_warmly() -> None:
    # BOB-066 2.6: a warm "это лучше у него спросить" on an owner_data request from a
    # guest — the tactful voice of the refusal, pointing them at the owner himself.
    folded = tactful_withhold_directive().casefold()
    assert "владел" in folded  # points at the owner


def test_tactful_withhold_directive_is_warm_not_a_dry_wall() -> None:
    # It must read as tact, not the dry stranger-wall: explicitly not rude/cold.
    folded = tactful_withhold_directive().casefold()
    assert "груб" in folded  # names the anti-goal (без грубости / не грубо)


def test_tactful_withhold_directive_is_voice_not_a_rule_list() -> None:
    directive = tactful_withhold_directive()
    assert "•" not in directive
    assert "- " not in directive


# --- disclosure_refusal_directive: the wired gate (такт разглашения, BOB-066 W.4) ---


def test_disclosure_refusal_folds_the_tactful_line_for_a_guest_owner_data_request() -> None:
    directive = disclosure_refusal_directive(is_guest=True, needs_owner_data=True)
    assert directive == tactful_withhold_directive()


def test_disclosure_refusal_is_empty_when_the_request_is_not_owner_data() -> None:
    # A guest asking anything non-private composes exactly as before (no withhold line).
    assert disclosure_refusal_directive(is_guest=True, needs_owner_data=False) == ""


def test_disclosure_refusal_is_empty_for_a_non_guest() -> None:
    # An owner / known peer asking about owner data is never walled — byte-identical.
    assert disclosure_refusal_directive(is_guest=False, needs_owner_data=True) == ""


def test_disclosure_refusal_is_empty_for_a_non_guest_non_owner_data_turn() -> None:
    assert disclosure_refusal_directive(is_guest=False, needs_owner_data=False) == ""


def test_recalled_impression_directive_carries_the_prior_note() -> None:
    # BOB-019 bob-apv.3: when a sender Bob has met before writes again, the prior
    # first-impression note is folded in so Bob recalls them wryly — the actual note
    # text must reach the line so the recall is grounded in what he really thought.
    note = "тот самый незнакомец, держался настороже"
    line = recalled_impression_directive(note)
    assert note in line


def test_recalled_impression_directive_signals_prior_contact() -> None:
    # It reads as recognition ("кажется, мы уже сталкивались"), not a fresh meeting.
    folded = recalled_impression_directive("впечатление").casefold()
    assert "уже" in folded or "снова" in folded or "прежд" in folded


def test_recalled_impression_directive_is_voice_not_a_rule_list() -> None:
    line = recalled_impression_directive("впечатление")
    assert "•" not in line
    assert "- " not in line


def test_engagement_directive_full_adds_no_line() -> None:
    # Full engagement is the default voice — it appends nothing.
    assert engagement_directive(EngagementLevel.FULL) == ""


def test_engagement_directive_playful_invites_banter() -> None:
    # BOB-014 .2a: a playful appetite reads as "up for banter / подурачиться".
    folded = engagement_directive(EngagementLevel.PLAYFUL).casefold()
    assert "подурач" in folded or "подыгр" in folded


def test_engagement_directive_terse_keeps_it_short() -> None:
    folded = engagement_directive(EngagementLevel.TERSE).casefold()
    assert "коротко" in folded


def test_engagement_directive_decline_winds_down_never_rude() -> None:
    # DECLINE softly winds the chatter down and is explicitly NOT rude (sulk is .2b).
    folded = engagement_directive(EngagementLevel.DECLINE).casefold()
    assert "заболтал" in folded or "не тянет" in folded
    assert "без груб" in folded


def test_engagement_directive_is_voice_not_a_rule_list() -> None:
    for level in (
        EngagementLevel.PLAYFUL,
        EngagementLevel.TERSE,
        EngagementLevel.DECLINE,
    ):
        line = engagement_directive(level)
        assert "•" not in line
        assert "- " not in line
    assert "\n" not in line


def test_sulk_directive_is_cold_and_curt() -> None:
    # BOB-014 .2b: while обижен Bob is quieter / curt — minimal, not warm.
    folded = sulk_directive(intensity=0.8).casefold()
    assert "обиж" in folded or "задел" in folded
    assert "суше" in folded or "коротко" in folded or "сдержан" in folded


def test_sulk_directive_is_never_a_reset_still_bob() -> None:
    # Cold-but-still-Bob: never a personality reset, never gratuitously rude.
    folded = sulk_directive(intensity=0.9).casefold()
    assert "всё ещё ты" in folded or "не сброс" in folded or "остаёшься собой" in folded
    assert "груб" in folded  # explicitly NOT rude (mentions без грубости)


def test_sulk_directive_is_voice_not_a_rule_list() -> None:
    line = sulk_directive(intensity=0.5)
    assert "•" not in line
    assert "\n" not in line


def test_profanity_stance_is_calm_about_casual_mat() -> None:
    # BOB-014 .2b: Bob is calm about casual мат (мат "с ним", not "на него") and may
    # quip back in his dry style — never offended by vocabulary.
    folded = profanity_stance().casefold()
    assert "мат" in folded
    assert "подкол" in folded or "поддел" in folded or "в том же" in folded


def test_profanity_stance_registers_directed_hostility() -> None:
    # He DOES register hostility aimed AT him (directed insults), unlike casual мат.
    folded = profanity_stance().casefold()
    assert "на тебя" in folded or "направлен" in folded or "оскорбл" in folded


def test_profanity_stance_is_voice_not_a_rule_list() -> None:
    line = profanity_stance()
    assert "•" not in line
    assert "\n" not in line


def _exemplar_lines(directive: str) -> list[str]:
    """The quoted few-shot exemplar lines inside the directive (between « »)."""
    lines: list[str] = []
    rest = directive
    while "«" in rest and "»" in rest:
        start = rest.index("«") + 1
        end = rest.index("»", start)
        lines.append(rest[start:end])
        rest = rest[end + 1 :]
    return lines


# --- brevity_directive (BOB-024) ---------------------------------------------


def test_brevity_directive_terse_is_a_strong_short_instruction() -> None:
    # TERSE → a STRONG instruction (not a soft hint): one short line, no preamble,
    # no lists, like a live person in a chat.
    folded = brevity_directive(Verbosity.TERSE).casefold()
    assert "коротк" in folded or "одной фраз" in folded or "одну строк" in folded
    assert "без" in folded  # без преамбул/списков/воды
    assert "как живой человек" in folded


def test_brevity_directive_expansive_permits_unfurling() -> None:
    folded = brevity_directive(Verbosity.EXPANSIVE).casefold()
    assert "развернут" in folded or "разверн" in folded or "подробн" in folded


def test_brevity_directive_normal_is_empty() -> None:
    # NORMAL is the neutral default — it adds no length directive of its own.
    assert brevity_directive(Verbosity.NORMAL) == ""


def test_brevity_directive_is_voice_not_a_rule_list() -> None:
    for verbosity in (Verbosity.TERSE, Verbosity.EXPANSIVE):
        assert "•" not in brevity_directive(verbosity)


# --- brevity_few_shot (BOB-024) ----------------------------------------------


def test_brevity_few_shot_terse_carries_short_answer_examples() -> None:
    # TERSE mixes in 2-3 "простой вопрос → КОРОТКИЙ ответ" exemplars — the main lever
    # against Qwen's verbosity prior (examples beat the directive).
    few_shot = brevity_few_shot(Verbosity.TERSE)
    examples = _exemplar_lines(few_shot)
    assert len(examples) >= 2
    # The model-facing examples are short — no long unfurling.
    assert all(len(example) <= 80 for example in examples)


def test_brevity_few_shot_normal_and_expansive_are_empty() -> None:
    # Few-shot is the TERSE lever only; NORMAL/EXPANSIVE add no examples.
    assert brevity_few_shot(Verbosity.NORMAL) == ""
    assert brevity_few_shot(Verbosity.EXPANSIVE) == ""


def test_brevity_few_shot_exemplars_are_russian_short_dialogue() -> None:
    # Guardrail (тон/язык): the TERSE few-shot stays Bob's voice — each exemplar is a
    # short «вопрос → ответ» dialogue pair in Russian (Cyrillic), never an English or
    # multi-line block, so it cannot drift Bob's language or tone.
    examples = _exemplar_lines(brevity_few_shot(Verbosity.TERSE))
    assert examples, "TERSE few-shot carries no exemplar pairs"
    for example in examples:
        assert "—" in example  # a «вопрос — ответ» pair, not a bare line
        assert "\n" not in example  # one short line, no unfurling
        assert any("а" <= ch.casefold() <= "я" for ch in example)  # Cyrillic, Russian


def test_brevity_directive_and_few_shot_are_one_signal_per_verbosity() -> None:
    # Guardrail (single length signal): for any verbosity at most ONE of directive /
    # few-shot is non-empty per role — TERSE pairs a directive WITH its short-answer
    # few-shot; NORMAL is silent; EXPANSIVE carries only a directive (no shots). There is
    # never a competing/contradictory length cue.
    assert brevity_directive(Verbosity.NORMAL) == ""
    assert brevity_few_shot(Verbosity.NORMAL) == ""
    # EXPANSIVE: directive licenses unfurling, NO short-answer few-shot to contradict it.
    assert brevity_directive(Verbosity.EXPANSIVE) != ""
    assert brevity_few_shot(Verbosity.EXPANSIVE) == ""
    # TERSE: directive + few-shot pull the SAME way (short), never against each other.
    assert brevity_directive(Verbosity.TERSE) != ""
    assert brevity_few_shot(Verbosity.TERSE) != ""
