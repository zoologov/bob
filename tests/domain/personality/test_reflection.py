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

from bob.domain.personality.reflection import (
    GENERIC_REFLECT_PROMPT,
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
