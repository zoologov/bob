# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the grounded reflection prompt builder (BOB-026 .2).

A pure, no-LLM function: given a little fresh context (recent episodes + the
current mood tone) it weaves a prompt that asks for ONE short introspective
sentence about "now" instead of the static generic template that produced the
same thought every ~5 min. With no fresh context it falls back to the generic
prompt verbatim — so an unwired tick behaves exactly as before.
"""

from __future__ import annotations

from random import Random

from bob.domain.personality.disposition import Disposition
from bob.domain.personality.reflection import (
    GENERIC_MONOLOGUE_PROMPT,
    GENERIC_REFLECT_PROMPT,
    LIVING_REFLECTION_EXAMPLES,
    REFLECTION_ANGLES,
    build_monologue_prompt,
    build_reflection_prompt,
    select_reflection_angle,
)


def test_no_context_falls_back_to_the_generic_prompt() -> None:
    # No recent episodes and no mood tone -> the legacy generic prompt, unchanged.
    assert build_reflection_prompt(recent_contents=(), mood_tone="") == GENERIC_REFLECT_PROMPT


def test_recent_episodes_are_woven_into_the_prompt() -> None:
    prompt = build_reflection_prompt(
        recent_contents=("owner: как дела?\nbob: норм", "тихо думал про орбиты"),
        mood_tone="content",
    )
    # The fresh context grounds the reflection so it is about NOW, not a template.
    assert "орбиты" in prompt
    assert "content" in prompt
    # Still asks for a single short introspective sentence.
    assert "one short" in prompt.casefold()


def test_blank_recent_contents_are_skipped() -> None:
    prompt = build_reflection_prompt(
        recent_contents=("", "   ", "реальная мысль"),
        mood_tone="",
    )
    assert "реальная мысль" in prompt
    # No mood tone -> no mood line, but the episode context still grounds it.
    assert prompt != GENERIC_REFLECT_PROMPT


def test_only_the_most_recent_contents_are_used_in_order() -> None:
    prompt = build_reflection_prompt(
        recent_contents=("первая", "вторая", "третья"),
        mood_tone="",
    )
    # All provided lines appear, oldest-first as given.
    assert prompt.index("первая") < prompt.index("вторая") < prompt.index("третья")


# --- BOB-033 .2: living reflections (few-shot palette + disposition valence-lean) ---


def test_disposition_weaves_a_few_shot_living_palette() -> None:
    # With a disposition wired, the grounded prompt carries 2-3 few-shot examples of a
    # "living Bob" private thought (a palette: curious / bright / wry / honestly sad) so
    # the Tier-0 model stops defaulting to monotone gloom.
    prompt = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        disposition=Disposition(optimism=0.8, resilience=0.7),
    )
    # BOB-047 .1: a handful, broadened to span several registers (not 2-3).
    assert 4 <= len(LIVING_REFLECTION_EXAMPLES) <= 7
    for example in LIVING_REFLECTION_EXAMPLES:
        assert example in prompt


def test_disposition_adds_an_honest_optimism_valence_lean() -> None:
    # A high-optimism disposition tilts the request toward a brighter thought, but the
    # instruction stays HONEST (lows are allowed) — never a scripted "be happy".
    prompt = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        disposition=Disposition(optimism=0.9, resilience=0.7),
    ).casefold()
    assert "optimism" in prompt
    assert "honest" in prompt


def test_disposition_lean_differs_by_optimism() -> None:
    # The valence-lean is DERIVED from optimism, not a fixed string: a strong optimist
    # and a weak one produce distinct prompts.
    bright = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        disposition=Disposition(optimism=0.9, resilience=0.7),
    )
    muted = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        disposition=Disposition(optimism=0.1, resilience=0.7),
    )
    assert bright != muted


def test_no_context_still_falls_back_even_with_a_disposition() -> None:
    # The no-context generic fallback is preserved: with no episode and no tone the
    # generic template is returned verbatim regardless of the disposition.
    assert (
        build_reflection_prompt(
            recent_contents=(),
            mood_tone="",
            disposition=Disposition(optimism=0.8, resilience=0.7),
        )
        == GENERIC_REFLECT_PROMPT
    )


def test_without_a_disposition_the_few_shot_palette_is_absent() -> None:
    # Backward-compatible: an unwired disposition keeps the prior grounded prompt
    # (no few-shot examples), so existing behaviour is unchanged.
    prompt = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
    )
    for example in LIVING_REFLECTION_EXAMPLES:
        assert example not in prompt


# --- BOB-061 .3: disposition is NOT the recurring-closer driver (empirical) ---
#
# The «пусть остаётся как есть / мне так спокойнее» closer recurs (BOB-061). It has
# two candidate drivers: (1) a TEXT-level recall/prompt echo — already handled by
# .1 (cross-session closer persist) + .2 (near-verbatim detect + strip + soft nudge);
# (2) a DISPOSITION lean — a semantic "leave-as-is / calmer that way" status-quo
# stance that would REGENERATE the motif after the text-level strip.
#
# Empirical finding (this bead): the Disposition value object is a two-trait affective
# vector (``optimism``, ``resilience``). Its ONLY textual surface into any prompt is the
# disposition-derived valence-lean in ``build_reflection_prompt`` — which leans toward
# OPTIMISM and explicitly permits a genuine low. There is NO status-quo/comfort/
# "leave-as-is" trait, derivation, or injected phrasing anywhere; disposition never
# enters the REPLY prompt at all (only the reflection/monologue + mood path), and
# reappraisal MOVES a dark thought to a constructive one rather than sticking it in a
# comfort rut. So disposition is NOT a driver of the recurring closer — the motif is a
# text/recall-mimicry phenomenon (few-shot exemplars + Bob's own recalled closers) that
# .1 + .2 address. These tests PIN that finding so a future edit that quietly injects a
# fixed comfort-closer stance into the disposition path would fail.

# Motif tokens of the recurring closer «(пусть) оста(ётся/нется/вить) как есть /
# (мне) так спокойнее» plus its English status-quo/comfort synonyms.
_COMFORT_CLOSER_MOTIF = (
    "как есть",
    "спокойнее",
    "оставить",
    "останется",
    "остаётся",
    "status quo",
    "leave as is",
    "leave it",
    "comfort",
    "calmer",
)


def test_disposition_lean_injects_no_fixed_comfort_closer_stance() -> None:
    # The disposition-derived text carries NO "leave-as-is / calmer that way" status-quo
    # stance for ANY temperament across the whole optimism range — confirming the
    # recurring closer is text-level, not a disposition lean.
    for optimism in (0.0, 0.1, 0.5, 0.8, 0.9, 1.0):
        prompt = build_reflection_prompt(
            recent_contents=("собрал телескоп",),
            mood_tone="content",
            disposition=Disposition(optimism=optimism, resilience=0.7),
        ).casefold()
        for token in _COMFORT_CLOSER_MOTIF:
            assert token not in prompt, (
                f"disposition path injected comfort-closer token {token!r} "
                f"at optimism={optimism}"
            )


def test_disposition_adds_nothing_a_bare_grounded_prompt_lacks_but_an_optimism_lean() -> None:
    # The disposition contributes ONLY the few-shot living palette + the optimism
    # valence-lean on TOP of the bare grounded prompt — no status-quo/comfort closer.
    # (Whatever the disposition adds beyond the bare prompt is optimism-honest, never a
    # canned closing stance.) So even the DELTA the disposition introduces is clean.
    bare = build_reflection_prompt(recent_contents=("собрал телескоп",), mood_tone="content")
    leaned = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        disposition=Disposition(optimism=0.8, resilience=0.7),
    )
    delta = leaned.replace(bare, "").casefold()
    assert "optimism" in delta  # the lean is present…
    for token in _COMFORT_CLOSER_MOTIF:
        assert token not in delta  # …and it carries no comfort-closer stance.


# --- BOB-047 .1: broadened palette + seeded angle variety ---


def test_living_palette_spans_several_distinct_registers() -> None:
    # The few-shot palette must carry RANGE (not one register) — a handful of distinct
    # thoughts so the model is not nudged into a single mood. All entries are unique.
    assert len(LIVING_REFLECTION_EXAMPLES) >= 4
    assert len(set(LIVING_REFLECTION_EXAMPLES)) == len(LIVING_REFLECTION_EXAMPLES)


def test_select_reflection_angle_is_deterministic_per_seed() -> None:
    # Same seed -> same angle (deterministic, like the BOB-033 reappraisal gate).
    assert select_reflection_angle(Random(7)) == select_reflection_angle(Random(7))  # noqa: S311


def test_select_reflection_angle_varies_across_seeds() -> None:
    # Across a sequence of seeds the angle ROTATES — more than one distinct mode is
    # produced, so reflections do not lock into a single register.
    produced = {select_reflection_angle(Random(seed)) for seed in range(20)}  # noqa: S311
    assert len(produced) >= 3
    assert produced <= set(REFLECTION_ANGLES)


def test_angle_is_woven_into_the_prompt_as_a_type_of_thought_directive() -> None:
    # The chosen angle appears in the grounded prompt as a light "kind of thought"
    # directive — it shapes the TYPE of thought, not a fixed canned sentence.
    angle = REFLECTION_ANGLES[0]
    prompt = build_reflection_prompt(
        recent_contents=("собрал телескоп",), mood_tone="content", angle=angle
    )
    assert angle in prompt


def test_different_angles_yield_different_prompts() -> None:
    # The angle is not a constant: distinct angles produce distinct prompts.
    a = build_reflection_prompt(
        recent_contents=("собрал телескоп",), mood_tone="content", angle=REFLECTION_ANGLES[0]
    )
    b = build_reflection_prompt(
        recent_contents=("собрал телескоп",), mood_tone="content", angle=REFLECTION_ANGLES[1]
    )
    assert a != b


def test_angle_keeps_mood_honesty_with_a_low_disposition() -> None:
    # Mood-honest: even with an angle AND a low-optimism disposition, the prompt still
    # PERMITS a low thought — the angle nudges the KIND, never forces positivity.
    prompt = build_reflection_prompt(
        recent_contents=("сегодня тихо",),
        mood_tone="subdued",
        disposition=Disposition(optimism=0.1, resilience=0.5),
        angle=REFLECTION_ANGLES[0],
    ).casefold()
    assert "honest" in prompt
    assert "low" in prompt


def test_no_context_falls_back_even_with_an_angle() -> None:
    # The no-context generic fallback is preserved regardless of a wired angle.
    assert (
        build_reflection_prompt(recent_contents=(), mood_tone="", angle=REFLECTION_ANGLES[0])
        == GENERIC_REFLECT_PROMPT
    )


# --- BOB-047 .2: acceptance/guardrails — register variety + mood honesty + palette ---


def test_palette_carries_both_a_bright_and_a_low_register() -> None:
    # Range, NOT forced positivity: the broadened palette must keep BOTH a clearly
    # bright thought AND an honestly low one, so a future edit cannot quietly collapse
    # it back into a single cheerful register (the failure mode BOB-047 fixes).
    palette = "\n".join(LIVING_REFLECTION_EXAMPLES)
    assert "улыбаюсь" in palette  # a clearly BRIGHT thought...
    assert "славно" in palette
    assert "тише, чем хотелось бы" in palette  # ...alongside an honestly LOW one
    # ...and at least three distinct registers in all (>= the bead's floor).
    assert len(set(LIVING_REFLECTION_EXAMPLES)) >= 3


def test_every_angle_preserves_mood_honesty_with_a_low_disposition() -> None:
    # The core mood-honesty guardrail: NO angle forces positivity. For EVERY angle in
    # the rotation, a low-optimism disposition + a subdued tone still yields a prompt
    # that explicitly PERMITS a low thought ("stay honest ... let the thought be low").
    for angle in REFLECTION_ANGLES:
        prompt = build_reflection_prompt(
            recent_contents=("сегодня тихо",),
            mood_tone="subdued",
            disposition=Disposition(optimism=0.05, resilience=0.5),
            angle=angle,
        ).casefold()
        assert "honest" in prompt
        assert "low" in prompt
        assert angle.casefold() in prompt  # the angle is woven in alongside the honesty


def test_angle_is_additive_to_grounding_and_mood() -> None:
    # The angle does NOT replace the NOW-grounding or the mood line — it is an extra
    # KIND-of-thought directive layered on top, so the reflection stays grounded.
    prompt = build_reflection_prompt(
        recent_contents=("собрал телескоп",),
        mood_tone="content",
        angle=REFLECTION_ANGLES[2],
    )
    assert "собрал телескоп" in prompt  # grounding preserved
    assert "content" in prompt  # mood preserved
    assert REFLECTION_ANGLES[2] in prompt  # angle added


def test_shared_rng_rotates_the_angle_and_is_deterministic_per_seed() -> None:
    # Register variety at the source: drawing repeatedly from ONE seeded RNG (as the
    # tick does tick-to-tick) ROTATES through several distinct angles — not one mode
    # repeated — and the whole sequence is reproducible for a given seed.
    def sequence(seed: int, n: int) -> list[str]:
        rng = Random(seed)  # noqa: S311
        return [select_reflection_angle(rng) for _ in range(n)]

    rolled = sequence(0, 12)
    assert len(set(rolled)) >= 3  # varies — does not lock into one register
    assert sequence(0, 12) == rolled  # same seed -> identical sequence (deterministic)
    assert sequence(1, 12) != rolled  # a different seed -> a different rotation


# --- BOB-029: mood-conditioned inner-monologue prompt ---


def test_monologue_no_tone_falls_back_to_the_generic_prompt() -> None:
    # Empty tone -> the legacy generic monologue prompt, byte-for-byte unchanged.
    assert build_monologue_prompt("") == GENERIC_MONOLOGUE_PROMPT
    assert build_monologue_prompt("   ") == GENERIC_MONOLOGUE_PROMPT


def test_monologue_carries_the_current_mood_tone() -> None:
    prompt = build_monologue_prompt("bright and buzzing")
    # The live mood is injected so the thought mirrors how Bob actually feels...
    assert "bright and buzzing" in prompt
    # ...and the model is explicitly told NOT to default to gloom (the old trap).
    assert "gloom" in prompt.casefold() or "melancholy" in prompt.casefold()
    # Still asks for the one-word sentiment classification the tick parses.
    for label in ("positive", "negative", "neutral"):
        assert label in prompt


def test_monologue_different_moods_yield_different_prompts() -> None:
    # A bright mood and a subdued mood must produce distinct, mood-specific prompts,
    # so the monologue genuinely mirrors the current mood rather than a fixed text.
    assert build_monologue_prompt("upbeat") != build_monologue_prompt("subdued")
