# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого ядра «куда писать» (BOB-090.B2).

Корень эпика: исходящего адреса не существовало как понятия — ответ всегда уходил в чат
текущего хода, и просьба «расскажи Норману в нашей группе» была невыполнима. Ядро решает
ОДИН вопрос: этот адрес известен однозначно — или надо переспросить?

🔴 Решение owner'а: при неоднозначности ПЕРЕСПРАШИВАТЬ, а не угадывать. Угаданный не тот
адресат — ровно тот класс ошибки, из-за которого заведён эпик. И писать в другой чат Боб
вправе только по просьбе owner'а (урок BOB-076).
"""

from __future__ import annotations

import pytest

from bob.social.destination import (
    DestinationKind,
    DestinationOutcome,
    DestinationVerdict,
    KnownDestination,
    resolve_destination,
)

_HERE = 555  # текущий чат хода (личка owner'а)

_GROUP = KnownDestination(
    chat_id=-1004372947307,
    topic_id=32,
    label="наша группа",
    kind=DestinationKind.GROUP,
)
_OTHER_GROUP = KnownDestination(
    chat_id=-1009999999999,
    topic_id=None,
    label="рабочий чат",
    kind=DestinationKind.GROUP,
)
_DM = KnownDestination(
    chat_id=_HERE, topic_id=None, label="личка", kind=DestinationKind.OWNER_DM
)


def _resolve(
    place: str, known: tuple[KnownDestination, ...], *, from_owner: bool = True
) -> DestinationVerdict:
    return resolve_destination(place, known, from_owner=from_owner, here_chat_id=_HERE)


# --- Однозначный адрес -------------------------------------------------------


def test_the_single_known_group_resolves_to_its_exact_address() -> None:
    # «в группу» = известная группа, вместе с её топиком: адрес точный, а не «чат вообще».
    verdict = _resolve("group", (_GROUP,))

    assert verdict.outcome is DestinationOutcome.RESOLVED
    assert verdict.address == _GROUP
    assert verdict.address is not None
    assert verdict.address.topic_id == 32
    assert verdict.note == ""


def test_the_owner_dm_resolves_when_it_is_not_the_current_chat() -> None:
    verdict = resolve_destination(
        "owner_dm", (_GROUP, _DM), from_owner=True, here_chat_id=_GROUP.chat_id
    )

    assert verdict.outcome is DestinationOutcome.RESOLVED
    assert verdict.address == _DM


@pytest.mark.parametrize("place", ["group", "GROUP", "  group  ", "группа", "группу"])
def test_the_place_argument_is_read_tolerantly(place: str) -> None:
    # Аргумент — закрытый перечень, который модель выбирает; регистр/пробелы/форма слова
    # не должны рождать лишнее «переспроси».
    assert _resolve(place, (_GROUP,)).outcome is DestinationOutcome.RESOLVED


# --- Неоднозначность: переспросить, а не угадать ------------------------------


def test_two_known_groups_are_never_guessed_between() -> None:
    # 🔴 Ядро правила: когда групп больше одной, Боб ПЕРЕСПРАШИВАЕТ.
    verdict = _resolve("group", (_GROUP, _OTHER_GROUP))

    assert verdict.outcome is DestinationOutcome.ASK
    assert verdict.address is None
    # Перечень меток — это и есть предметность вопроса: обе, через запятую.
    assert verdict.note == (
        "Не отправляй. Переспроси, в какой именно чат написать. "
        "Известные: наша группа, рабочий чат."
    )


def test_an_unknown_place_asks_instead_of_picking_anything() -> None:
    verdict = _resolve("канал про котиков", (_GROUP,))

    assert verdict.outcome is DestinationOutcome.ASK
    assert verdict.address is None
    # Подсказка обязана СКАЗАТЬ, что делать: «переспроси», а не молчаливый отказ.
    assert verdict.note == (
        "Не отправляй. Переспроси, в какой именно чат написать."
    )


def test_a_place_with_no_known_address_asks() -> None:
    # Просят в личку, а личка не настроена: подставлять группу нельзя.
    verdict = _resolve("owner_dm", (_GROUP,))

    assert verdict.outcome is DestinationOutcome.ASK
    assert verdict.address is None


def test_no_known_destinations_at_all_asks() -> None:
    verdict = _resolve("group", ())

    assert verdict.outcome is DestinationOutcome.ASK
    # Перечислять нечего — вопрос остаётся вопросом, без пустого «Известные: .»
    assert verdict.note == "Не отправляй. Переспроси, в какой именно чат написать."


def test_an_empty_place_asks() -> None:
    verdict = _resolve("", (_GROUP,))

    assert verdict.outcome is DestinationOutcome.ASK
    assert verdict.note


def test_the_ask_note_never_names_a_single_candidate_as_the_answer() -> None:
    # Подсказка модели — это ВОПРОС, а не готовый выбор: «отправь» в ней быть не должно.
    note = _resolve("group", (_GROUP, _OTHER_GROUP)).note

    assert "Не отправляй" in note


# --- Только по просьбе owner'а (BOB-076) --------------------------------------


def test_a_non_owner_can_never_route_a_message_elsewhere() -> None:
    verdict = _resolve("group", (_GROUP,), from_owner=False)

    assert verdict.outcome is DestinationOutcome.REFUSED
    assert verdict.address is None
    # Отказ обязан назвать причину — иначе Боб не сможет объяснить её своими словами.
    assert "только по просьбе Вовы" in verdict.note


def test_a_non_owner_is_refused_even_when_the_address_is_unambiguous() -> None:
    # Отказ по owner'у идёт ПЕРВЫМ: однозначность адреса его не отменяет.
    for place in ("group", "owner_dm", "чушь"):
        assert (
            _resolve(place, (_GROUP, _DM), from_owner=False).outcome
            is DestinationOutcome.REFUSED
        )


# --- «Это тот же чат» ---------------------------------------------------------


def test_the_current_chat_is_refused_structurally_not_by_wording() -> None:
    # Совпадение chat_id — структурный признак «ты уже здесь»; отдельного слова «здесь»
    # ядро не знает и знать не должно.
    verdict = resolve_destination(
        "group", (_GROUP,), from_owner=True, here_chat_id=_GROUP.chat_id
    )

    assert verdict.outcome is DestinationOutcome.REFUSED
    assert verdict.address is None
    assert "здесь" in verdict.note


def test_same_chat_different_topic_is_still_the_same_chat() -> None:
    verdict = resolve_destination(
        "group",
        (KnownDestination(_GROUP.chat_id, 77, "наша группа", DestinationKind.GROUP),),
        from_owner=True,
        here_chat_id=_GROUP.chat_id,
    )

    assert verdict.outcome is DestinationOutcome.REFUSED


# --- Детерминизм --------------------------------------------------------------


def test_the_same_inputs_always_yield_the_same_verdict() -> None:
    first = _resolve("group", (_GROUP, _OTHER_GROUP))
    second = _resolve("group", (_GROUP, _OTHER_GROUP))

    assert first == second
