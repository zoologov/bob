# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты ядра «кто говорит» — Боб или GUPPI (BOB-090.D1).

Канон Денниса Тейлора: GUPPI — несознательный интерфейс без личности, мнения и
инициативы. Отсюда линия раздела: МЕХАНИКА (сырой вывод инструментов, пошаговый
нарратив прогона, технический статус/итог, «не найдено», техническое подтверждение)
звучит GUPPI, сухо и фактически; всё ЖИВОЕ и адресованное людям — Бобом.

🔴 Вердикт — enum, а mutmut подмену члена перечисления не порождает вовсе
(MUTATION.md, урок bob-abk.34). Поэтому соответствие «вид сообщения → говорящий»
держится ЭТИМИ содержательными юнитами (полная таблица истинности по всем видам,
пересчёт состава каждой стороны), а не цифрой score.
"""

from __future__ import annotations

import pytest

from bob.coding.speaker import MessageKind, Speaker, is_mechanical, speaker_for

# Полная таблица истинности канона: КАЖДЫЙ вид сообщения назван явно, чтобы новый вид
# нельзя было завести молча — тест ниже требует, чтобы таблица покрывала весь enum.
_CANON: dict[MessageKind, Speaker] = {
    # Механика — сухой исполнитель.
    MessageKind.TOOL_OUTPUT: Speaker.GUPPI,
    MessageKind.RUN_EVENT: Speaker.GUPPI,
    MessageKind.RUN_STATUS: Speaker.GUPPI,
    MessageKind.NOTHING_FOUND: Speaker.GUPPI,
    MessageKind.TECHNICAL_ACK: Speaker.GUPPI,
    # Живое и адресованное людям — Боб.
    MessageKind.SESSION_GATE: Speaker.BOB,
    MessageKind.MODE_NOTICE: Speaker.BOB,
    MessageKind.REACTION: Speaker.BOB,
    MessageKind.PRESENCE_MARK: Speaker.BOB,
    MessageKind.PERMISSION_REQUEST: Speaker.BOB,
    MessageKind.ADDRESSED_TO_PERSON: Speaker.BOB,
}


@pytest.mark.parametrize(("kind", "expected"), list(_CANON.items()))
def test_speaker_for_follows_the_canon_table(kind: MessageKind, expected: Speaker) -> None:
    assert speaker_for(kind) is expected


def test_canon_table_covers_every_kind() -> None:
    # Новый вид сообщения обязан получить сторону явно — иначе он молча уехал бы к Бобу.
    assert set(_CANON) == set(MessageKind)


def test_mechanical_side_is_exactly_the_five_machine_kinds() -> None:
    mechanical = {kind for kind in MessageKind if speaker_for(kind) is Speaker.GUPPI}
    assert mechanical == {
        MessageKind.TOOL_OUTPUT,
        MessageKind.RUN_EVENT,
        MessageKind.RUN_STATUS,
        MessageKind.NOTHING_FOUND,
        MessageKind.TECHNICAL_ACK,
    }


def test_live_side_is_exactly_the_six_human_kinds() -> None:
    live = {kind for kind in MessageKind if speaker_for(kind) is Speaker.BOB}
    assert live == {
        MessageKind.SESSION_GATE,
        MessageKind.MODE_NOTICE,
        MessageKind.REACTION,
        MessageKind.PRESENCE_MARK,
        MessageKind.PERMISSION_REQUEST,
        MessageKind.ADDRESSED_TO_PERSON,
    }


def test_permission_request_is_bob_not_mechanics() -> None:
    """🔴 Зафиксировано owner'ом ДО реализации (BOB-090, срез E опирается на это).

    Просьба разрешения — социальный акт: Боб защищает приватность owner'а и просит
    решения у ЧЕЛОВЕКА. Механика — «инструмент вернул пусто», а не «человек просит
    доступ», поэтому запрос разрешения никогда не уходит сухим голосом GUPPI.
    """
    assert speaker_for(MessageKind.PERMISSION_REQUEST) is Speaker.BOB
    assert speaker_for(MessageKind.PERMISSION_REQUEST) is not speaker_for(
        MessageKind.NOTHING_FOUND
    )


def test_is_mechanical_agrees_with_the_verdict() -> None:
    # Предикат и вердикт — одна политика, а не две расходящиеся копии.
    for kind in MessageKind:
        assert is_mechanical(kind) is (speaker_for(kind) is Speaker.GUPPI)


def test_speakers_are_two_distinct_voices() -> None:
    # Ровно два голоса, и оба названы: третьего «служебного» лица в каноне нет.
    assert {speaker.value for speaker in Speaker} == {"bob", "guppi"}
