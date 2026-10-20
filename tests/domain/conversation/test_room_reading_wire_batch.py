# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the BATCH half of the reflective wire (BOB-072).

``build_batch_room_prompt`` folds an attributed ambient burst into a Tier-1 stream-read
prompt; ``parse_batch_reading`` maps the model's per-block reply back to one
:class:`RoomReading` per message. 🔴 Unlike the single-message parser (which RAISES on
garbage for the periphery gate's safe-default), the BATCH parser is TOLERANT: a garbled or
missing block for a message degrades to a safe silent IGNORE for THAT message, and a wholly
unparseable reply degrades to an all-IGNORE reading of the right length — Bob never acts on a
guessed batch read, and the plan always matches the burst.
"""

from __future__ import annotations

from bob.conversation.room_reading import (
    BatchAmbientMessage,
    BatchRoomReadingContext,
    ReflectiveIntent,
    RoomMood,
)
from bob.conversation.room_reading_wire import (
    BATCH_ROOM_READ_SYSTEM_PROMPT,
    build_batch_room_prompt,
    parse_batch_reading,
)
from bob.kernel.interlocutor import InterlocutorKind


def _msg(
    *,
    sender_id: int,
    sender_name: str,
    text: str,
    ts: float = 0.0,
    kind: InterlocutorKind | None = None,
) -> BatchAmbientMessage:
    return BatchAmbientMessage(
        sender_id=sender_id,
        sender_name=sender_name,
        text=text,
        ts=ts,
        floor_holder="other",
        floor_participant=True,
        interest=0.4,
        kind=kind,
    )


def _ctx(*messages: BatchAmbientMessage) -> BatchRoomReadingContext:
    return BatchRoomReadingContext(
        messages=tuple(messages),
        recent_thread="Norman: привет",
        mood_tone="ровный",
        others_present=True,
    )


# --- build_batch_room_prompt -----------------------------------------------------------


def test_prompt_numbers_and_attributes_every_message() -> None:
    ctx = _ctx(
        _msg(sender_id=6, sender_name="Norman", text="зонды скучные"),
        _msg(sender_id=7, sender_name="Riker", text="да ладно тебе"),
    )
    prompt = build_batch_room_prompt(ctx)
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "Norman" in prompt
    assert "Riker" in prompt
    assert "зонды скучные" in prompt
    assert "да ладно тебе" in prompt


def test_prompt_carries_the_shared_thread_and_tone() -> None:
    prompt = build_batch_room_prompt(_ctx(_msg(sender_id=6, sender_name="N", text="hi")))
    assert "Norman: привет" in prompt
    assert "ровный" in prompt


def test_prompt_marks_a_guest_author_so_a_warm_reply_reads_as_salient() -> None:
    # 🔴 BOB-078 B: батч-read должен ЗНАТЬ, что автор — гость/новичок, иначе тёплая реплика
    # («Ты классный») читается как низкая salience → IGNORE (живой баг Лилии). Рядом с автором
    # проступает маркер «гость».
    prompt = build_batch_room_prompt(
        _ctx(
            _msg(
                sender_id=8080,
                sender_name="Лиля",
                text="Ты классный",
                kind=InterlocutorKind.GUEST,
            )
        )
    )
    assert "Лиля" in prompt
    assert "гость" in prompt


def test_prompt_omits_a_kind_marker_for_an_insider_or_unknown_kind() -> None:
    # Владелец/знакомый/неизвестный kind — без пометки (baseline): маркер только для аутсайдера.
    for kind in (None, InterlocutorKind.OWNER, InterlocutorKind.KNOWN):
        prompt = build_batch_room_prompt(
            _ctx(_msg(sender_id=6, sender_name="Norman", text="hi", kind=kind))
        )
        assert "гость" not in prompt
        assert "бот" not in prompt


def test_prompt_marks_a_bot_author() -> None:
    prompt = build_batch_room_prompt(
        _ctx(_msg(sender_id=9, sender_name="Guppi", text="ok", kind=InterlocutorKind.BOT))
    )
    assert "бот" in prompt


def test_batch_read_prompt_states_the_participant_engagement_rule() -> None:
    # 🔴 BOB-078 B: соц-значимую реплику участника (комплимент/знакомство/«ты» к Бобу) не
    # игнорировать; в чужой кросс-ток («ты» к третьему) — не влезать. Правило живёт в промпте.
    assert "комплимент" in BATCH_ROOM_READ_SYSTEM_PROMPT
    assert "кросс-ток" in BATCH_ROOM_READ_SYSTEM_PROMPT
    # Существующий баланс сохранён.
    assert "Не отвечай на всё" in BATCH_ROOM_READ_SYSTEM_PROMPT


# --- parse_batch_reading: valid ---------------------------------------------------------


def test_parses_one_reading_per_message_in_order() -> None:
    raw = (
        "mood: warm\n"
        "intent: reply\n"
        "salience: 0.8\n"
        "reason: интересно\n"
        "---\n"
        "intent: react\n"
        "salience: 0.6\n"
        "emoji: 🔥\n"
        "---\n"
        "intent: ignore\n"
        "salience: 0.1\n"
    )
    batch = parse_batch_reading(raw, 3)
    assert len(batch.readings) == 3
    assert batch.readings[0].intent is ReflectiveIntent.REPLY
    assert batch.readings[1].intent is ReflectiveIntent.REACT
    assert batch.readings[1].emoji == "🔥"
    assert batch.readings[2].intent is ReflectiveIntent.IGNORE
    assert batch.room_mood is RoomMood.WARM


def test_missing_block_for_a_message_degrades_to_ignore() -> None:
    # Only two blocks returned for a three-message burst → the third is a safe IGNORE.
    raw = "intent: reply\nsalience: 0.8\n---\nintent: reply\nsalience: 0.9\n"
    batch = parse_batch_reading(raw, 3)
    assert len(batch.readings) == 3
    assert batch.readings[2].intent is ReflectiveIntent.IGNORE
    assert batch.readings[2].salience == 0.0


# --- parse_batch_reading: garbage → tolerant all-IGNORE ---------------------------------


def test_wholly_unparseable_reply_yields_all_ignore_of_right_length() -> None:
    batch = parse_batch_reading("I cannot read this room at all", 3)
    assert len(batch.readings) == 3
    assert all(r.intent is ReflectiveIntent.IGNORE for r in batch.readings)
    assert batch.room_mood is RoomMood.NEUTRAL


def test_one_garbled_block_only_ignores_that_message() -> None:
    raw = (
        "intent: reply\nsalience: 0.8\n"
        "---\n"
        "totally garbled, no intent no salience\n"
        "---\n"
        "intent: react\nsalience: 0.7\nemoji: 👍\n"
    )
    batch = parse_batch_reading(raw, 3)
    assert batch.readings[0].intent is ReflectiveIntent.REPLY
    assert batch.readings[1].intent is ReflectiveIntent.IGNORE
    assert batch.readings[2].intent is ReflectiveIntent.REACT


def test_empty_batch_yields_empty_reading() -> None:
    batch = parse_batch_reading("", 0)
    assert batch.readings == ()
