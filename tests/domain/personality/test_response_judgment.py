# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure response-judgment wire protocol (BOB-049 .1).

Covers the three pure domain pieces of the semantic response-judgment seam: the
Tier-0 prompt builder (folds message + sender + thread + hints + mood), the reply
parser (model output -> ``ResponseChoice``, robust to whitespace/case, raising on
garbage), and emoji validation against the Telegram free-reaction set.
"""

from __future__ import annotations

import pytest

from bob.conversation.addressivity import Addressivity
from bob.conversation.response_choice import (
    ResponseContext,
    ResponseIntent,
)
from bob.conversation.response_judgment import (
    DEFAULT_WARM_EMOJI,
    RESPONSE_JUDGE_SYSTEM_PROMPT,
    ResponseJudgeParseError,
    build_judgment_user_prompt,
    parse_response_choice,
    validate_reaction_emoji,
)
from bob.social.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)


def _context(
    *,
    text: str = "как настроение, Боб?",
    name: str = "Боб-старший",
    kind: InterlocutorKind = InterlocutorKind.OWNER,
    trust: Trust = Trust.TRUSTED,
    recent_thread: str = "Боб-старший: привет\nbob: привет!",
    mentions_bob: bool = True,
    reply_to_bob: bool = False,
    addressivity: Addressivity = Addressivity.DIRECTED_TO_BOB,
    others_present: bool = False,
    floor_engaged: bool = True,
    mood_tone: str = "cheerful",
) -> ResponseContext:
    interlocutor = Interlocutor(
        sender_id=1, display_name=name, kind=kind, trust=trust
    )
    return ResponseContext(
        text=text,
        interlocutor=interlocutor,
        recent_thread=recent_thread,
        mentions_bob=mentions_bob,
        reply_to_bob=reply_to_bob,
        addressivity=addressivity,
        others_present=others_present,
        floor_engaged=floor_engaged,
        mood_tone=mood_tone,
    )


# --- prompt builder ----------------------------------------------------------


def test_prompt_includes_message_sender_thread_hints_and_mood() -> None:
    prompt = build_judgment_user_prompt(
        _context(
            text="ну что, поехали?",
            name="Норман",
            kind=InterlocutorKind.GUEST,
            recent_thread="Норман: привет\nbob: здравствуй",
            mentions_bob=False,
            reply_to_bob=True,
            addressivity=Addressivity.DIRECTED_TO_OTHER,
            others_present=True,
            floor_engaged=False,
            mood_tone="glum",
        )
    )
    # message text
    assert "ну что, поехали?" in prompt
    # sender social context
    assert "Норман" in prompt
    assert InterlocutorKind.GUEST.value in prompt
    # per-person thread snippet
    assert "здравствуй" in prompt
    # structural hints
    assert Addressivity.DIRECTED_TO_OTHER.value in prompt
    assert "reply_to_bob" in prompt
    assert "others_present" in prompt
    assert "floor" in prompt
    # mood tone
    assert "glum" in prompt


def test_system_prompt_names_the_three_intents() -> None:
    lowered = RESPONSE_JUDGE_SYSTEM_PROMPT.lower()
    assert "reply" in lowered
    assert "react" in lowered
    assert "ignore" in lowered


# --- parser ------------------------------------------------------------------


def test_parses_reply() -> None:
    choice = parse_response_choice("intent: reply\nreason: addressed to Bob")
    assert choice.intent is ResponseIntent.REPLY
    assert choice.emoji is None
    assert "addressed" in choice.reason


def test_parses_ignore() -> None:
    choice = parse_response_choice("intent: ignore\nreason: not for Bob")
    assert choice.intent is ResponseIntent.IGNORE
    assert choice.emoji is None


def test_parses_react_with_emoji() -> None:
    choice = parse_response_choice("intent: react\nemoji: 🔥\nreason: warm")
    assert choice.intent is ResponseIntent.REACT
    assert choice.emoji == "🔥"


def test_parser_is_robust_to_whitespace_and_case() -> None:
    choice = parse_response_choice("  INTENT :  Reply  \n")
    assert choice.intent is ResponseIntent.REPLY


def test_parser_accepts_bare_intent_word() -> None:
    choice = parse_response_choice("react ❤")
    assert choice.intent is ResponseIntent.REACT
    assert choice.emoji == "❤"


def test_react_with_emoji_outside_set_falls_back_to_default_warm() -> None:
    choice = parse_response_choice("intent: react\nemoji: 👽\nreason: alien")
    assert choice.intent is ResponseIntent.REACT
    assert choice.emoji == DEFAULT_WARM_EMOJI


def test_react_without_emoji_falls_back_to_default_warm() -> None:
    choice = parse_response_choice("intent: react\nreason: just a nod")
    assert choice.intent is ResponseIntent.REACT
    assert choice.emoji == DEFAULT_WARM_EMOJI


@pytest.mark.parametrize("raw", ["", "   ", "maybe?", "I think you should answer"])
def test_unparseable_output_raises(raw: str) -> None:
    with pytest.raises(ResponseJudgeParseError):
        parse_response_choice(raw)


# --- emoji validation --------------------------------------------------------


def test_in_set_emoji_validates_to_itself() -> None:
    assert validate_reaction_emoji("🔥") == "🔥"


def test_emoji_with_variation_selector_is_normalized() -> None:
    # ❤️ = U+2764 U+FE0F; the free-reaction set stores the bare ❤.
    assert validate_reaction_emoji("❤️") == "❤"


def test_out_of_set_emoji_is_none() -> None:
    assert validate_reaction_emoji("👽") is None


def test_none_and_blank_emoji_are_none() -> None:
    assert validate_reaction_emoji(None) is None
    assert validate_reaction_emoji("   ") is None
