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

from bob.domain.personality.disposition import Disposition
from bob.domain.personality.reflection import (
    GENERIC_MONOLOGUE_PROMPT,
    GENERIC_REFLECT_PROMPT,
    LIVING_REFLECTION_EXAMPLES,
    build_monologue_prompt,
    build_reflection_prompt,
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
    assert 2 <= len(LIVING_REFLECTION_EXAMPLES) <= 3
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
