# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure reaction-judgment wire protocol (BOB-050 .2).

Covers the two pure domain pieces of the semantic reaction seam: the Tier-0 prompt
builder (folds emoji + added/removed + Bob's message + reactor + thread) and the reply
parser (model output -> ``ReactionMeaning`` with a BOUNDED, meaning-derived mood delta
+ warmth nudge, raising on garbage). The effect comes from the named MEANING, never an
emoji table.
"""

from __future__ import annotations

import pytest

from bob.personality.reaction_judgment import (
    REACTION_JUDGE_SYSTEM_PROMPT,
    ReactionJudgeParseError,
    build_reaction_user_prompt,
    parse_reaction_meaning,
)
from bob.personality.reaction_meaning import ReactionContext
from bob.social.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)


def _ctx(
    *,
    emoji: tuple[str, ...] = ("❤",),
    added: bool = True,
    bob_message_text: str = "я правда рад, что ты написал",
    kind: InterlocutorKind = InterlocutorKind.OWNER,
    warmth: float | None = 0.3,
) -> ReactionContext:
    reactor = Interlocutor(
        sender_id=1,
        display_name="Боб-старший",
        kind=kind,
        trust=Trust.TRUSTED,
    )
    return ReactionContext(
        emoji=emoji,
        added=added,
        bob_message_text=bob_message_text,
        reactor=reactor,
        reactor_warmth=warmth,
        recent_thread="Боб-старший: привет\nbob: привет!",
    )


def test_prompt_folds_emoji_action_and_message() -> None:
    prompt = build_reaction_user_prompt(_ctx(emoji=("🔥",), added=False))

    assert "🔥" in prompt
    assert "removed" in prompt  # the action is surfaced (removal leans negative)
    assert "я правда рад, что ты написал" in prompt
    assert "Боб-старший" in prompt
    # The system prompt forbids an emoji table and names the removal nuance.
    assert "table" in REACTION_JUDGE_SYSTEM_PROMPT.casefold()
    assert "removed" in REACTION_JUDGE_SYSTEM_PROMPT.casefold()


def test_prompt_handles_unknown_warmth() -> None:
    prompt = build_reaction_user_prompt(_ctx(warmth=None))
    assert "unknown" in prompt


def test_parses_warm_meaning_into_positive_bounded_delta() -> None:
    meaning = parse_reaction_meaning(
        "interpretation: его тронуло\nsentiment: warm\nintensity: high\nacknowledge: yes"
    )

    assert meaning.interpretation == "его тронуло"
    assert meaning.mood_delta.valence > 0
    assert meaning.mood_delta.social > 0  # warmth lifts sociability a touch
    assert meaning.warmth_nudge > 0
    assert meaning.worth_acknowledging is True
    # Bounded: even the strongest reaction is a small nudge (no swings, BOB-030).
    assert meaning.mood_delta.valence <= 0.25
    assert abs(meaning.warmth_nudge) <= 0.12


def test_parses_dismissive_meaning_into_negative_delta() -> None:
    meaning = parse_reaction_meaning(
        "interpretation: насмешка\nsentiment: dismissive\nintensity: medium\nacknowledge: no"
    )

    assert meaning.mood_delta.valence < 0
    assert meaning.mood_delta.social == 0.0  # a cold read does not lift sociability
    assert meaning.warmth_nudge < 0
    assert meaning.worth_acknowledging is False


def test_withdrawn_reaction_reads_negative() -> None:
    # A removal the judge names "withdrawn"/"uncertain" leans mildly negative.
    meaning = parse_reaction_meaning(
        "interpretation: передумал\nsentiment: withdrawn\nintensity: low\nacknowledge: no"
    )
    assert meaning.mood_delta.valence < 0


def test_neutral_meaning_is_flat() -> None:
    meaning = parse_reaction_meaning(
        "interpretation: просто отметил\nsentiment: neutral\nintensity: low\nacknowledge: no"
    )
    assert meaning.mood_delta.valence == 0.0
    assert meaning.warmth_nudge == 0.0


def test_acknowledge_only_when_positive() -> None:
    # acknowledge=yes on a negative read must not flag a being-received moment.
    meaning = parse_reaction_meaning(
        "interpretation: укол\nsentiment: hurt\nintensity: high\nacknowledge: yes"
    )
    assert meaning.worth_acknowledging is False


def test_intensity_defaults_when_missing() -> None:
    meaning = parse_reaction_meaning("interpretation: тепло\nsentiment: warm\nacknowledge: no")
    assert meaning.mood_delta.valence == pytest.approx(0.15)  # medium default


def test_raises_without_interpretation() -> None:
    with pytest.raises(ReactionJudgeParseError):
        parse_reaction_meaning("sentiment: warm\nintensity: high")


def test_raises_on_unrecognised_sentiment() -> None:
    with pytest.raises(ReactionJudgeParseError):
        parse_reaction_meaning("interpretation: что-то\nsentiment: ???\nintensity: low")


def test_raises_when_sentiment_label_is_absent() -> None:
    # An interpretation but no sentiment line at all -> a real failure signal (the
    # decorative path drops it) rather than a guessed default.
    with pytest.raises(ReactionJudgeParseError):
        parse_reaction_meaning("interpretation: что-то\nintensity: low")


def test_parser_is_case_and_whitespace_tolerant() -> None:
    meaning = parse_reaction_meaning(
        "  Interpretation:  тепло \n  Sentiment: WARM \n  Intensity: Low "
    )
    assert meaning.interpretation == "тепло"
    assert meaning.mood_delta.valence > 0
