# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого ядра упоминаний (BOB-090.B3).

Живой дефект (эпизод 3088): Боб написал «@Норман», хотя ник человека — ``@NormanGri``.
Он не выдумывал злонамеренно — @username не хранился НИГДЕ, так что тег было неоткуда
взять, и модель дописала правдоподобное.

🔴 Правило: **выдуманный тег хуже отсутствующего.** Если ника нет, обращаемся по имени;
если тег в тексте не подтверждён ростером — снимаем «собаку», а не оставляем ложный тег.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.social.first_impression import FirstImpression
from bob.social.mention import (
    PersonHandle,
    ground_mentions,
    handles_from,
    mention_for,
)

_NORMAN = PersonHandle(name="Норман", username="NormanGri")
_LILYA = PersonHandle(name="Лиля", username=None)
_PASHA = PersonHandle(name="Паша Иванов", username="pasha_i")


# --- mention_for: как обратиться ---------------------------------------------


def test_a_known_person_is_addressed_by_their_real_handle() -> None:
    assert mention_for("Норман", (_NORMAN, _LILYA)) == "@NormanGri"


def test_the_lookup_ignores_case() -> None:
    assert mention_for("норман", (_NORMAN,)) == "@NormanGri"


def test_a_person_without_a_username_is_addressed_by_name() -> None:
    # 🔴 В Telegram username необязателен: тега нет — значит по имени, и никак иначе.
    assert mention_for("Лиля", (_NORMAN, _LILYA)) == "Лиля"


def test_an_unknown_person_is_addressed_by_the_name_given() -> None:
    assert mention_for("Игорь", (_NORMAN,)) == "Игорь"


def test_a_full_name_is_matched_by_its_first_word_too() -> None:
    # В ростере «Паша Иванов», в просьбе — «Паша».
    assert mention_for("Паша", (_PASHA,)) == "@pasha_i"


def test_an_empty_name_yields_nothing_to_address() -> None:
    assert mention_for("", (_NORMAN,)) == ""


def test_the_handle_is_never_composed_out_of_a_name() -> None:
    # Ядро эпизода 3088: из имени тег НЕ делается ни при каких условиях.
    for name in ("Норман", "Лиля", "Игорь"):
        result = mention_for(name, (_LILYA,))
        assert result in {name, f"@{_LILYA.username}"}
        assert result != f"@{name}"


# --- ground_mentions: чинить исходящий текст ----------------------------------


def test_an_invented_tag_is_replaced_by_the_real_handle() -> None:
    # Ровно эпизод 3088.
    assert (
        ground_mentions("@Норман, глянь, пожалуйста", (_NORMAN,))
        == "@NormanGri, глянь, пожалуйста"
    )


def test_a_correct_handle_is_left_untouched() -> None:
    text = "@NormanGri, глянь"
    assert ground_mentions(text, (_NORMAN,)) == text


def test_a_correct_handle_survives_a_case_difference() -> None:
    assert ground_mentions("@normangri, привет", (_NORMAN,)) == "@normangri, привет"


def test_a_tag_for_someone_without_a_username_loses_its_at_sign() -> None:
    # Тега нет — остаётся имя. Ложный тег не оставляем.
    assert ground_mentions("@Лиля, привет", (_LILYA,)) == "Лиля, привет"


def test_an_unbacked_tag_loses_its_at_sign() -> None:
    assert ground_mentions("@Игорь, привет", (_NORMAN,)) == "Игорь, привет"


def test_several_mentions_are_each_resolved_on_their_own() -> None:
    assert (
        ground_mentions("@Норман и @Лиля — оба", (_NORMAN, _LILYA))
        == "@NormanGri и Лиля — оба"
    )


def test_text_without_mentions_is_returned_byte_for_byte() -> None:
    text = "Обычный ответ без тегов: e-mail bob@example.com, цена 5@шт."
    assert ground_mentions(text, (_NORMAN,)) is text


def test_an_email_is_not_a_mention() -> None:
    text = "пиши на norman@example.com"
    assert ground_mentions(text, (_NORMAN,)) == text


def test_an_empty_roster_strips_every_unbacked_tag() -> None:
    assert ground_mentions("@Норман, привет", ()) == "Норман, привет"


@pytest.mark.parametrize("text", ["@", "@ Норман", "почта@", "стоит 100@"])
def test_a_lone_at_sign_is_left_alone(text: str) -> None:
    assert ground_mentions(text, (_NORMAN,)) == text


def test_grounding_is_idempotent() -> None:
    once = ground_mentions("@Норман, глянь", (_NORMAN,))
    assert ground_mentions(once, (_NORMAN,)) == once


# --- handles_from: ростер как источник ----------------------------------------


def _impression(
    sender_id: int, name: str | None, username: str | None, note: str = "кто-то"
) -> FirstImpression:
    return FirstImpression(
        sender_id=sender_id,
        first_seen_at=datetime(2026, 8, 1, tzinfo=UTC),
        note=note,
        display_name=name,
        username=username,
    )


def test_handles_are_read_off_the_roster() -> None:
    handles = handles_from((_impression(1, "Норман", "NormanGri"),))

    assert handles == (PersonHandle(name="Норман", username="NormanGri"),)


def test_a_legacy_row_without_a_display_name_still_yields_a_name() -> None:
    # Имя падает обратно на голову заметки «{имя} — …» (тот же фолбэк, что у ростера).
    handles = handles_from(
        (_impression(2, None, "lil_ya", note="Лиля — кто-то из знакомых."),)
    )

    assert handles == (PersonHandle(name="Лиля", username="lil_ya"),)


def test_a_person_with_no_username_keeps_an_empty_handle() -> None:
    assert handles_from((_impression(3, "Лиля", None),))[0].username is None


def test_a_nameless_row_is_dropped_rather_than_addressed_as_nothing() -> None:
    assert handles_from((_impression(4, "", None, note=" — "),)) == ()
