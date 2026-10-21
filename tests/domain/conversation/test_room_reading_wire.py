# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure «read the room» wire protocol (BOB-066 Срез 2.2).

Covers the two pure domain pieces of the reflective seam: the Tier-1 prompt builder
(folds message + sender + shared thread + hints + floor hints + mood + interest) and
the reply parser (model output → ``RoomReading``, robust to whitespace/case, 🔴 RAISING
on a missing/garbled intent or salience rather than silently defaulting).
"""

from __future__ import annotations

import pytest

from bob.conversation.addressivity import Addressivity
from bob.conversation.response_judgment import DEFAULT_WARM_EMOJI
from bob.conversation.room_reading import (
    ReflectiveIntent,
    RoomMood,
    RoomReadingContext,
)
from bob.conversation.room_reading_wire import (
    ROOM_READ_SYSTEM_PROMPT,
    RoomReadingParseError,
    build_room_prompt,
    parse_room_reading,
)
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust

_FULL = (
    "situation: ребята обсуждают фильм\n"
    "pairings: Norman↔Lyosha, Lyosha↔Vladimir\n"
    "mood: playful\n"
    "intent: reply\n"
    "addressee: 6\n"
    "salience: 0.72\n"
    "wants_web: no\n"
    "reason: тема мне близка"
)


# --- happy path ---------------------------------------------------------------


def test_parses_a_full_labelled_reading() -> None:
    reading = parse_room_reading(_FULL)
    assert reading.situation == "ребята обсуждают фильм"
    assert reading.pairings == ("Norman↔Lyosha", "Lyosha↔Vladimir")
    assert reading.room_mood is RoomMood.PLAYFUL
    assert reading.intent is ReflectiveIntent.REPLY
    assert reading.addressee_id == 6
    assert reading.salience == pytest.approx(0.72)
    assert reading.wants_web is False
    assert reading.reason == "тема мне близка"


def test_labels_are_case_insensitive_and_whitespace_tolerant() -> None:
    reading = parse_room_reading("  INTENT :  Ignore \n Salience: 0.5 ")
    assert reading.intent is ReflectiveIntent.IGNORE
    assert reading.salience == pytest.approx(0.5)


# --- intent is REQUIRED (raises) ---------------------------------------------


def test_missing_intent_raises() -> None:
    with pytest.raises(RoomReadingParseError):
        parse_room_reading("mood: warm\nsalience: 0.5")


def test_garbled_intent_raises() -> None:
    with pytest.raises(RoomReadingParseError):
        parse_room_reading("intent: whatever\nsalience: 0.5")


# --- salience is REQUIRED (raises) -------------------------------------------


def test_missing_salience_raises() -> None:
    with pytest.raises(RoomReadingParseError):
        parse_room_reading("intent: reply")


def test_non_numeric_salience_raises() -> None:
    with pytest.raises(RoomReadingParseError):
        parse_room_reading("intent: reply\nsalience: very high")


def test_salience_above_one_is_clamped_down() -> None:
    assert parse_room_reading("intent: reply\nsalience: 1.8").salience == 1.0


def test_salience_below_zero_is_clamped_up() -> None:
    assert parse_room_reading("intent: reply\nsalience: -0.4").salience == 0.0


# --- soft fields degrade gracefully ------------------------------------------


def test_unknown_mood_degrades_to_neutral() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\nmood: ecstatic")
    assert reading.room_mood is RoomMood.NEUTRAL


def test_absent_mood_degrades_to_neutral() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5")
    assert reading.room_mood is RoomMood.NEUTRAL


def test_absent_pairings_are_empty() -> None:
    assert parse_room_reading("intent: reply\nsalience: 0.5").pairings == ()


def test_pairings_split_on_comma_and_semicolon_and_trim() -> None:
    reading = parse_room_reading(
        "intent: reply\nsalience: 0.5\npairings: a↔b ; c↔d , e↔f"
    )
    assert reading.pairings == ("a↔b", "c↔d", "e↔f")


def test_addressee_none_token_is_none() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\naddressee: none")
    assert reading.addressee_id is None


def test_addressee_absent_is_none() -> None:
    assert parse_room_reading("intent: reply\nsalience: 0.5").addressee_id is None


def test_addressee_numeric_is_parsed() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\naddressee: 42")
    assert reading.addressee_id == 42


@pytest.mark.parametrize("token", ["yes", "да", "true", "Y"])
def test_wants_web_affirmatives_are_true(token: str) -> None:
    reading = parse_room_reading(f"intent: reply\nsalience: 0.5\nwants_web: {token}")
    assert reading.wants_web is True


@pytest.mark.parametrize("token", ["no", "нет", "maybe", ""])
def test_wants_web_non_affirmatives_are_false(token: str) -> None:
    reading = parse_room_reading(f"intent: reply\nsalience: 0.5\nwants_web: {token}")
    assert reading.wants_web is False


def test_absent_wants_web_is_false() -> None:
    assert parse_room_reading("intent: reply\nsalience: 0.5").wants_web is False


# --- REACT emoji validation ---------------------------------------------------


def test_react_keeps_a_valid_in_set_emoji() -> None:
    reading = parse_room_reading("intent: react\nsalience: 0.5\nemoji: 🔥")
    assert reading.emoji == "🔥"


def test_react_without_a_valid_emoji_falls_back_to_the_warm_default() -> None:
    reading = parse_room_reading("intent: react\nsalience: 0.5\nemoji: 🧿")
    assert reading.emoji == DEFAULT_WARM_EMOJI


def test_react_with_no_emoji_line_falls_back_to_the_warm_default() -> None:
    reading = parse_room_reading("intent: react\nsalience: 0.5")
    assert reading.emoji == DEFAULT_WARM_EMOJI


def test_non_react_intent_has_no_emoji() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\nemoji: 🔥")
    assert reading.emoji is None


# --- robustness: tokens carry trailing punctuation / stray tokens ------------


def test_intent_tolerates_trailing_punctuation() -> None:
    assert parse_room_reading("intent: reply.\nsalience: 0.5").intent is (
        ReflectiveIntent.REPLY
    )


def test_mood_tolerates_trailing_punctuation() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\nmood: warm!")
    assert reading.room_mood is RoomMood.WARM


def test_addressee_tolerates_trailing_punctuation() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\naddressee: 6.")
    assert reading.addressee_id == 6


def test_addressee_skips_a_non_numeric_token_before_the_id() -> None:
    # A stray word before the id must not abort the scan (continue, not break).
    reading = parse_room_reading("intent: reply\nsalience: 0.5\naddressee: user 42")
    assert reading.addressee_id == 42


def test_wants_web_tolerates_trailing_punctuation() -> None:
    reading = parse_room_reading("intent: reply\nsalience: 0.5\nwants_web: yes.")
    assert reading.wants_web is True


def test_absent_situation_is_the_empty_string() -> None:
    assert parse_room_reading("intent: reply\nsalience: 0.5").situation == ""


def test_absent_reason_is_the_empty_string() -> None:
    assert parse_room_reading("intent: reply\nsalience: 0.5").reason == ""


# --- prompt builder -----------------------------------------------------------


def _ctx() -> RoomReadingContext:
    sender = Interlocutor(
        sender_id=6,
        display_name="Norman",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )
    return RoomReadingContext(
        text="да ну, зонды скучные",
        interlocutor=sender,
        recent_thread="Norman: привет\nbob: хай",
        mood_tone="ровный",
        addressivity=Addressivity.AMBIENT,
        mentions_bob=False,
        reply_to_bob=False,
        others_present=True,
        floor_engaged=False,
        floor_holder="other",
        floor_participant=True,
        interest=0.42,
    )


def test_prompt_carries_the_message_and_the_structural_hints() -> None:
    prompt = build_room_prompt(_ctx())
    assert "да ну, зонды скучные" in prompt
    assert "Norman" in prompt
    assert "addressivity: ambient" in prompt
    assert "floor_holder: other" in prompt
    assert "floor_participant: yes" in prompt
    assert "topic_interest: 0.42" in prompt


def test_system_prompt_names_the_five_intents() -> None:
    for intent in ("reply", "react", "ignore", "initiate", "self_check"):
        assert intent in ROOM_READ_SYSTEM_PROMPT
