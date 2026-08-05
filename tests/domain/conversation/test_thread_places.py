# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты «нить несёт место» — чистое ядро пометки реплик (BOB-090.C3).

Живой дефект (эпизоды 3331/3333, 2026-08-05): owner в ЛИЧКЕ просит «расскажи в группе»,
Боб отвечает шуткой в личку, а на повтор просьбы заявляет «я же только что рассказал
ГРУППЕ». Он не соврал — недавняя нить приезжала в промпт БЕЗ пометки места, и сказанное
наедине читалось как сказанное при всех.

Здесь проверяется чистое ядро: каждая реплика нити несёт место, где прозвучала, обе
стороны симметрично (личное не выдаётся за публичное И наоборот), а НЕИЗВЕСТНОЕ место
(легаси-строка с ``visibility IS NULL``) молчит — правило среза C1: молчание о месте
честно, выдуманное место и есть дефект.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.reply_context import _assemble_shareable_context
from bob.conversation.thread_places import (
    PLACE_PRIVATE_MARK,
    PLACE_ROOM_MARK,
    THREAD_PLACES_LEGEND,
    thread_block,
)
from bob.kernel.visibility import VISIBILITY_OWNER_PRIVATE, VISIBILITY_PUBLIC
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine

if TYPE_CHECKING:
    from collections.abc import Mapping

_PRIVATE_TURN = "Вова: расскажи ребятам в группе, чем занимались\nbob: про выключенный свет"
_ROOM_TURN = "Лиля: всем привет\nbob: привет!"


def _turn(content: str, visibility: str | None) -> Mapping[str, object]:
    """Реплика нити ровно в той форме, в какой её отдаёт архив эпизодов."""
    item: dict[str, object] = {"content": content, "event_type": "message"}
    if visibility is not None:
        item["visibility"] = visibility
    return item


# --- Место у каждой реплики -----------------------------------------------------


def test_a_turn_said_in_the_dm_is_marked_as_the_dm() -> None:
    block = thread_block([_turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE)], mark_places=True)

    assert f"{PLACE_PRIVATE_MARK} {_PRIVATE_TURN}" in block


def test_a_turn_said_in_the_room_is_marked_as_the_room() -> None:
    # 🔴 Обратный случай: сказанное при всех не должно выдаваться за сказанное наедине.
    block = thread_block([_turn(_ROOM_TURN, VISIBILITY_PUBLIC)], mark_places=True)

    assert f"{PLACE_ROOM_MARK} {_ROOM_TURN}" in block
    assert PLACE_PRIVATE_MARK not in block


def test_a_mixed_thread_keeps_each_turn_with_its_own_place() -> None:
    # Нить смешана всегда: Боб один разум и видит обе стороны — он должен ЗНАТЬ, где что
    # было, а не получить общее предупреждение «где-то как-то».
    block = thread_block(
        [
            _turn(_ROOM_TURN, VISIBILITY_PUBLIC),
            _turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE),
        ],
        mark_places=True,
    )

    assert f"{PLACE_ROOM_MARK} {_ROOM_TURN}" in block
    assert f"{PLACE_PRIVATE_MARK} {_PRIVATE_TURN}" in block


def test_the_place_words_survive_case_and_padding() -> None:
    # Метка приезжает из БД: разница в написании не должна отмывать место.
    block = thread_block([_turn(_ROOM_TURN, "  PUBLIC  ")], mark_places=True)

    assert f"{PLACE_ROOM_MARK} {_ROOM_TURN}" in block


def test_the_legend_explains_the_marks_and_forbids_swapping_the_places() -> None:
    block = thread_block([_turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE)], mark_places=True)

    assert THREAD_PLACES_LEGEND in block
    # Ровно тот дефект, из-за которого заведена беада: просьбу «скажи в группе» Боб счёл
    # выполненной, потому что сказал это в личке.
    assert "в общий чат это ещё не попадало" in THREAD_PLACES_LEGEND


# --- Неизвестное место молчит (правило C1) --------------------------------------


def test_a_legacy_turn_without_a_label_is_not_credited_to_the_room() -> None:
    # ``visibility IS NULL`` — «место неизвестно», а НЕ «сказано при всех».
    block = thread_block([_turn(_ROOM_TURN, None)], mark_places=True)

    assert PLACE_ROOM_MARK not in block
    assert PLACE_PRIVATE_MARK not in block


def test_an_unrecognised_label_says_nothing_about_the_place() -> None:
    block = thread_block([_turn(_ROOM_TURN, "secret")], mark_places=True)

    assert PLACE_ROOM_MARK not in block
    assert PLACE_PRIVATE_MARK not in block


def test_a_thread_with_no_known_place_reads_exactly_as_before() -> None:
    # Ни одной метки — легенда была бы шумом: блок совпадает с выключенным путём.
    history = [_turn(_ROOM_TURN, None), _turn(_PRIVATE_TURN, "secret")]

    assert thread_block(history, mark_places=True) == thread_block(history)


# --- Выключенный путь: байт-в-байт ----------------------------------------------


def test_the_off_path_is_the_thread_exactly_as_it_was() -> None:
    history = [
        _turn(_ROOM_TURN, VISIBILITY_PUBLIC),
        _turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE),
    ]

    assert thread_block(history) == f"Recent conversation:\n{_ROOM_TURN}\n{_PRIVATE_TURN}"


def test_an_empty_thread_adds_nothing_either_way() -> None:
    assert thread_block(()) == ""
    assert thread_block((), mark_places=True) == ""


def test_a_row_with_no_content_is_not_replayed() -> None:
    history = [_turn("", VISIBILITY_PUBLIC), _turn(_ROOM_TURN, VISIBILITY_PUBLIC)]

    assert thread_block(history, mark_places=True).count(PLACE_ROOM_MARK) == 1


def test_a_thread_of_silence_only_adds_nothing() -> None:
    # Все строки пустые — блока нет вовсе (а не пустой заголовок с легендой).
    assert thread_block([_turn("", VISIBILITY_PUBLIC)], mark_places=True) == ""


# --- Место доезжает до контекста ответа -----------------------------------------


def _soul() -> SOUL:
    return SOUL(identity="Боб", mood=Mood(), mood_baseline=Mood(), taste=TasteEngine())


def test_the_context_carries_the_place_of_every_turn() -> None:
    context = _assemble_shareable_context(
        _soul(),
        "группа",
        (),
        [
            _turn(_ROOM_TURN, VISIBILITY_PUBLIC),
            _turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE),
        ],
        mark_places=True,
    )

    assert f"{PLACE_ROOM_MARK} {_ROOM_TURN}" in context
    assert f"{PLACE_PRIVATE_MARK} {_PRIVATE_TURN}" in context
    assert THREAD_PLACES_LEGEND in context


def test_the_context_without_the_flag_is_the_context_as_it_was() -> None:
    history = [
        _turn(_ROOM_TURN, VISIBILITY_PUBLIC),
        _turn(_PRIVATE_TURN, VISIBILITY_OWNER_PRIVATE),
    ]

    context = _assemble_shareable_context(_soul(), "группа", (), history)

    assert f"Recent conversation:\n{_ROOM_TURN}\n{_PRIVATE_TURN}" in context
    assert PLACE_ROOM_MARK not in context
    assert PLACE_PRIVATE_MARK not in context
