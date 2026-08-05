# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты гейта переноса приватного в публичный чат (BOB-090.B4).

🔴 Решение owner'а: перенос считается **ПО МАТЕРИАЛУ, а не по форме**. Если в материал
ответа попал приватный эпизод, а адресат публичный — нужно согласие; пересказ своими
словами такой же перенос, как цитата. Иначе просьба «расскажи Норману, о чём мы говорили»
обходила бы гейт простой переформулировкой.

Материал хода — это ДВА источника: припомненное (recall) и сам разговор, в котором Боб
сейчас находится (личка owner'а приватна целиком). Оба учитываются.
"""

from __future__ import annotations

import pytest

from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    carries_owner_private,
    transfer_needs_consent,
)

_PRIVATE = {"content": "то, что Вова сказал в личке", "visibility": VISIBILITY_OWNER_PRIVATE}
_PUBLIC = {"content": "сказано в общем чате", "visibility": VISIBILITY_PUBLIC}
_LEGACY = {"content": "старая запись без метки", "visibility": None}


# --- carries_owner_private ----------------------------------------------------


def test_a_private_item_makes_the_material_private() -> None:
    assert carries_owner_private((_PUBLIC, _PRIVATE)) is True


def test_public_and_legacy_material_is_not_private() -> None:
    assert carries_owner_private((_PUBLIC, _LEGACY)) is False


def test_empty_material_is_not_private() -> None:
    assert carries_owner_private(()) is False


def test_the_private_label_is_read_case_insensitively() -> None:
    assert carries_owner_private(({"visibility": "Owner_Private"},)) is True


def test_a_missing_visibility_key_reads_as_not_private() -> None:
    # NULL/отсутствие метки = public (сквозная память BOB-051), как и у may_surface.
    assert carries_owner_private(({"content": "без метки"},)) is False


# --- transfer_needs_consent ---------------------------------------------------


def test_private_material_into_a_public_room_needs_consent() -> None:
    assert (
        transfer_needs_consent(
            (_PRIVATE,), turn_visibility=VISIBILITY_PUBLIC, destination_public=True
        )
        is True
    )


def test_a_private_conversation_needs_consent_even_with_public_recall() -> None:
    # 🔴 Материал — это и сам разговор: личка приватна целиком, пересказ её содержимого
    # в комнату остаётся переносом, даже если recall ничего приватного не поднял.
    assert (
        transfer_needs_consent(
            (_PUBLIC,),
            turn_visibility=VISIBILITY_OWNER_PRIVATE,
            destination_public=True,
        )
        is True
    )


def test_public_material_into_a_public_room_needs_no_consent() -> None:
    assert (
        transfer_needs_consent(
            (_PUBLIC, _LEGACY),
            turn_visibility=VISIBILITY_PUBLIC,
            destination_public=True,
        )
        is False
    )


def test_a_private_destination_never_needs_consent() -> None:
    # Отправка в личку самому owner'у — не перенос: аудитория не изменилась.
    assert (
        transfer_needs_consent(
            (_PRIVATE,),
            turn_visibility=VISIBILITY_OWNER_PRIVATE,
            destination_public=False,
        )
        is False
    )


def test_nothing_at_all_needs_no_consent() -> None:
    assert (
        transfer_needs_consent((), turn_visibility=None, destination_public=True)
        is False
    )


@pytest.mark.parametrize("destination_public", [True, False])
def test_the_verdict_is_deterministic(destination_public: bool) -> None:
    first = transfer_needs_consent(
        (_PRIVATE, _PUBLIC),
        turn_visibility=VISIBILITY_OWNER_PRIVATE,
        destination_public=destination_public,
    )
    second = transfer_needs_consent(
        (_PRIVATE, _PUBLIC),
        turn_visibility=VISIBILITY_OWNER_PRIVATE,
        destination_public=destination_public,
    )
    assert first == second == destination_public


def test_a_reworded_retelling_is_the_same_transfer_as_a_quote() -> None:
    # Гейт смотрит на МЕТКУ материала, а не на текст: переформулировка его не обходит.
    quote = transfer_needs_consent(
        ({"content": "дословно: …", "visibility": VISIBILITY_OWNER_PRIVATE},),
        turn_visibility=VISIBILITY_PUBLIC,
        destination_public=True,
    )
    retelling = transfer_needs_consent(
        ({"content": "если коротко, суть в том…", "visibility": VISIBILITY_OWNER_PRIVATE},),
        turn_visibility=VISIBILITY_PUBLIC,
        destination_public=True,
    )
    assert quote is retelling is True
