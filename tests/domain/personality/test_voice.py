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

from datetime import UTC, datetime

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
    formatting_directive,
    guppi_canon,
    improvement_directive,
    operator_stance,
    profanity_stance,
    recall_has_self_action,
    recall_has_work,
    recalled_impression_directive,
    recalled_self_action_directive,
    recalled_work_directive,
    relationship_tone_directive,
    roster_directive,
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
from bob.social.roster import RosterMember


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


# --- BOB-087.B2: Bob's OPERATOR stance toward GUPPI ---------------------------
# The positive framing that Bob is the human OPERATOR who DIRECTS GUPPI (the
# executor takes the mechanical firehose) and REACTS to the milestones in his own
# voice — never a robotic per-edit narrator. It strengthens the BOB-074 anti-
# narration guard into a stance, so the contract pins presence of the operator
# framing + the reinforced "don't narrate step-by-step", never exact wording.


def test_operator_stance_frames_bob_as_director_of_guppi() -> None:
    # Bob DIRECTS GUPPI — he is the operator, GUPPI the executor he steers.
    folded = operator_stance().casefold()
    assert "оператор" in folded
    assert "guppi" in folded
    assert "направля" in folded or "рул" in folded  # он направляет / рулит GUPPI


def test_operator_stance_reinforces_no_step_by_step_narration() -> None:
    # 🔴 BOB-074 guard, strengthened into a positive stance: Bob does NOT retell
    # GUPPI's work line-by-line (that firehose is GUPPI's channel now); his lines
    # are short human REACTIONS, not a log/journal.
    folded = operator_stance().casefold()
    assert "построчн" in folded or "пошагов" in folded
    assert "реакци" in folded
    assert "журнал" in folded or "лог" in folded


def test_operator_stance_reacts_to_milestones_in_bobs_voice() -> None:
    # The human milestone reactions (взялся / позеленело / сломалось / готово-PR)
    # are seeded as FLAVOR — Bob reacts as himself, not a status printer.
    folded = operator_stance().casefold()
    assert "веха" in folded or "вех" in folded
    assert "готов" in folded


def test_operator_stance_is_voice_not_a_rule_list() -> None:
    # Written as voice (mirroring the other directives), never a bullet checklist.
    directive = operator_stance()
    assert "•" not in directive
    assert "- " not in directive


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
    for accessor in (
        anti_bait_directive,
        variable_form_directive,
        guppi_canon,
        operator_stance,
    ):
        folded = accessor().casefold()
        assert not (
            "пусть остаётся как есть" in folded and "мне так спокойнее" in folded
        )


@pytest.mark.parametrize(
    "accessor",
    [anti_bait_directive, variable_form_directive, guppi_canon, operator_stance],
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


# --- BOB-080: multi-person roster directive -----------------------------------


_ROSTER_NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def _roster_member(name: str, *, is_newcomer: bool = True) -> RosterMember:
    return RosterMember(
        sender_id=abs(hash(name)) % 100_000,
        name=name,
        first_seen_at=_ROSTER_NOW,
        is_newcomer=is_newcomer,
    )


def test_roster_directive_empty_roster_adds_no_line() -> None:
    # BOB-080 INV-4: no recent joiners → no roster line (nothing to hold in mind).
    assert roster_directive(()) == ""


def test_roster_directive_names_the_recent_members() -> None:
    # The recalled people are NAMED so Bob can call them out himself, by name.
    line = roster_directive((_roster_member("Лиля"), _roster_member("Паша")))
    assert "Лиля" in line
    assert "Паша" in line


def test_roster_directive_frames_naming_by_occasion_not_a_flood() -> None:
    # INV-4 framing: name them BY the social occasion, never drag them in unprompted.
    folded = roster_directive((_roster_member("Лиля"),)).casefold()
    assert "по имени" in folded
    assert "без повода" in folded


def test_roster_directive_is_voice_not_a_rule_list() -> None:
    line = roster_directive((_roster_member("Лиля"), _roster_member("Паша")))
    assert "•" not in line
    assert "- " not in line


def test_roster_directive_names_only_newcomers_under_joined_framing() -> None:
    # BOB-080.6 honesty (S2): under the "недавно зашли" framing name ONLY the
    # fresh newcomers — an old acquaintance within the limit must NOT be announced
    # as if he just turned up.
    line = roster_directive(
        (
            _roster_member("Лиля", is_newcomer=True),
            _roster_member("Norman", is_newcomer=False),
            _roster_member("Алексей", is_newcomer=False),
        )
    )
    assert "Лиля" in line
    assert "Norman" not in line, f"старожил подан как только что зашедший: {line!r}"
    assert "Алексей" not in line, f"старожил подан как только что зашедший: {line!r}"


def test_roster_directive_names_all_when_all_are_newcomers() -> None:
    # An all-newcomer roster names everyone (nothing is falsely dropped).
    line = roster_directive(
        (_roster_member("Лиля", is_newcomer=True), _roster_member("Паша", is_newcomer=True))
    )
    assert "Лиля" in line
    assert "Паша" in line


def test_roster_directive_empty_when_no_newcomers() -> None:
    # Defensive: even if the roster carried only old-timers, an honest render frames
    # nobody as "just joined" — the line is empty rather than mislabelling.
    line = roster_directive(
        (
            _roster_member("Norman", is_newcomer=False),
            _roster_member("Алексей", is_newcomer=False),
        )
    )
    assert line == ""


# --- BOB-079.4: recalled self_action ownership directive ----------------------
#
# When recall surfaces one of Bob's OWN past deeds (event_type/category
# ``self_action``), the light voice directive backstops INV-1/2/3: he speaks of it
# in the first person as his own act, honestly owns a slip, does not blame external
# forces, and never confabulates a deed absent from memory.


def test_recall_has_self_action_true_when_a_self_action_is_present() -> None:
    recalled = [
        {"content": "Ada любит чай", "category": "preference"},
        {"content": "я доделал «X», открыл PR", "category": "self_action"},
    ]
    assert recall_has_self_action(recalled) is True


def test_recall_has_self_action_false_when_none_present() -> None:
    recalled = [
        {"content": "Ada любит чай", "category": "preference"},
        {"content": "Ada: привет", "category": "message"},
    ]
    assert recall_has_self_action(recalled) is False


def test_recall_has_self_action_is_case_insensitive_on_category() -> None:
    recalled = [{"content": "я взялся за «X»", "category": "SELF_ACTION"}]
    assert recall_has_self_action(recalled) is True


def test_recall_has_self_action_empty_is_false() -> None:
    assert recall_has_self_action([]) is False


def test_recall_has_self_action_ignores_memory_with_no_category() -> None:
    assert recall_has_self_action([{"content": "что-то"}]) is False


def test_recalled_self_action_directive_asserts_first_person_ownership() -> None:
    # INV-1/2: recalled self-actions are Bob's OWN deeds — spoken in the first person,
    # a slip honestly owned, never attributed to external forces.
    folded = recalled_self_action_directive().casefold()
    assert "от первого лица" in folded
    assert "призна" in folded  # честно признай (промах)
    assert "внешним силам" in folded


def test_recalled_self_action_directive_forbids_confabulation() -> None:
    # INV-3: Bob must not invent a deed that is not in memory.
    folded = recalled_self_action_directive().casefold()
    assert "не выдумывай" in folded


def test_recalled_self_action_directive_is_voice_not_a_rule_list() -> None:
    line = recalled_self_action_directive()
    assert "•" not in line
    assert "- " not in line


# --- BOB-087.C3: recalled work provenance directive (anti-confabulation) -------
#
# The mirror of the self_action directive for register-aware recall (slice C): when
# recall surfaces one of Bob's OWN ``work`` dev episodes (his operator recollection of
# directing GUPPI), a LIGHT voice line backstops against confabulation — he speaks of
# it in the first person as his REAL work with GUPPI, honestly owns a failure, and never
# invents details he does not remember. Independent of the self_action directive: work
# episodes carry event_type ``work`` (not ``self_action``), so both may fire at once.


def test_recall_has_work_true_on_work_category() -> None:
    recalled = [
        {"content": "Ada любит чай", "category": "preference"},
        {"content": "я попросил GUPPI поднять лимит — позеленело", "category": "work"},
    ]
    assert recall_has_work(recalled) is True


def test_recall_has_work_true_on_work_tag() -> None:
    # A work episode is also recognised by its provenance TAG, not only category.
    recalled = [{"content": "я правил runner", "tags": ["dev", "actor:bob"]}]
    assert recall_has_work(recalled) is True


def test_recall_has_work_false_on_self_action() -> None:
    # Independence: a self_action deed is NOT a work episode (distinct event_type).
    recalled = [{"content": "я доделал «X», открыл PR", "category": "self_action"}]
    assert recall_has_work(recalled) is False


def test_recall_has_work_false_on_casual_memory() -> None:
    recalled = [
        {"content": "Ada любит чай", "category": "preference"},
        {"content": "Ada: привет", "category": "message"},
    ]
    assert recall_has_work(recalled) is False


def test_recall_has_work_empty_is_false() -> None:
    assert recall_has_work([]) is False


def test_recall_has_work_ignores_memory_with_no_category_or_tags() -> None:
    assert recall_has_work([{"content": "что-то"}]) is False


def test_recall_has_work_is_case_insensitive_on_category() -> None:
    assert recall_has_work([{"content": "я собрал", "category": "WORK"}]) is True


def test_self_action_directive_signal_is_independent_of_work() -> None:
    # A work episode does NOT trip the self_action signal (distinct event_type).
    work = [{"content": "я попросил GUPPI", "category": "work"}]
    assert recall_has_self_action(work) is False


def test_recalled_work_directive_asserts_first_person_real_work_with_guppi() -> None:
    # It IS Bob's REAL operator work with GUPPI — first person, his own doing.
    folded = recalled_work_directive().casefold()
    assert "от первого лица" in folded
    assert "guppi" in folded


def test_recalled_work_directive_owns_failures_honestly() -> None:
    folded = recalled_work_directive().casefold()
    assert "сбо" in folded  # честно про сбои


def test_recalled_work_directive_forbids_confabulation() -> None:
    # The direct attack on the owner's fear: no invented details from memory Bob lacks.
    folded = recalled_work_directive().casefold()
    assert "не выдумывай" in folded


def test_recalled_work_directive_is_voice_not_a_rule_list() -> None:
    line = recalled_work_directive()
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


def test_brevity_expansive_licenses_structure_not_only_paragraphs() -> None:
    # BOB-086.2: length and STRUCTURE are distinct axes. EXPANSIVE now licenses
    # STRUCTURING substantive content (list / table / headings) rather than only
    # permitting more paragraphs — so a structural answer is shaped, not a prose wall.
    folded = brevity_directive(Verbosity.EXPANSIVE).casefold()
    assert "список" in folded or "списком" in folded
    assert "таблиц" in folded
    # The "можно развернуться" unfurling spirit is preserved (regression guard).
    assert "развернуться" in folded


# --- formatting_directive (BOB-086.2) ----------------------------------------


def test_formatting_directive_names_the_telegram_rich_palette() -> None:
    # BOB-086.2: teach Bob that Telegram supports rich formatting — the palette must
    # name lists, `код`/code-blocks, and TABLES (markdown `| … |` renders natively).
    folded = formatting_directive().casefold()
    assert "список" in folded or "списк" in folded  # lists (- / 1.)
    assert "таблиц" in folded  # markdown tables render natively
    assert "код" in folded  # `код`/code blocks + моно for paths/commands
    assert "заголов" in folded  # headings


def test_formatting_directive_judges_by_content_and_spares_casual() -> None:
    # 🔴 INV-1: format for the READER, judged BY CONTENT — structural content gets a
    # list / table / headings; ordinary chatter stays a short live line WITHOUT markup.
    folded = formatting_directive().casefold()
    assert "содержим" in folded  # judge by content
    # casual conversation stays живой and unformatted (no format-for-format's-sake).
    assert "жив" in folded  # живым коротким текстом
    assert "не форматируй" in folded or "не ради" in folded


def test_formatting_directive_is_voice_not_a_rule_list() -> None:
    # Consistent with the other voice helpers: guidance prose, never a bulleted rulebook.
    assert "•" not in formatting_directive()
