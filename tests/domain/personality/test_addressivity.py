# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Addressivity — кому адресовано сообщение (BOB-023).

Чистый детектор: :func:`classify_addressivity` отображает сигналы Telegram
(reply-to / @mention / имя-обращение) на :class:`Addressivity`
(DIRECTED_TO_BOB / DIRECTED_TO_OTHER / AMBIENT). Детерминирован, без I/O.
:func:`others_present` — лёгкая эвристика «есть ли в недавней истории НЕ текущий
отправитель» (не 1:1).
"""

from __future__ import annotations

from bob.domain.personality.addressivity import (
    Addressivity,
    classify_addressivity,
    others_present,
)

_BOB_ID = 100
_OTHER_ID = 200


# --- DIRECTED_TO_BOB ---------------------------------------------------------


def test_mention_is_directed_to_bob() -> None:
    # @mention Боба → прямо к нему, даже без reply / имени.
    result = classify_addressivity(
        text="что думаешь?",
        mentions_bob=True,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_reply_to_bob_is_directed_to_bob() -> None:
    # Реплай НА сообщение Боба → адресовано Бобу.
    result = classify_addressivity(
        text="ага",
        mentions_bob=False,
        reply_to_sender_id=_BOB_ID,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_name_address_at_start_is_directed_to_bob() -> None:
    # Имя-обращение в начале («Боб, …») → к Бобу.
    for text in ("Боб, привет", "боб, что скажешь", "Bob, hey", "BOB, look"):
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=True,
        )
        assert result is Addressivity.DIRECTED_TO_BOB, text


def test_name_address_without_comma_is_not_directed() -> None:
    # «Боб классный» (без запятой-обращения) — это НЕ обращение к Бобу, а про него.
    result = classify_addressivity(
        text="Боб классный парень",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.AMBIENT


def test_mention_wins_even_when_reply_to_other() -> None:
    # Явный @mention Боба перевешивает reply на другого.
    result = classify_addressivity(
        text="смотри",
        mentions_bob=True,
        reply_to_sender_id=_OTHER_ID,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


# --- DIRECTED_TO_OTHER -------------------------------------------------------


def test_reply_to_other_is_directed_to_other() -> None:
    # Реплай на сообщение ДРУГОГО человека → к другому.
    result = classify_addressivity(
        text="согласен",
        mentions_bob=False,
        reply_to_sender_id=_OTHER_ID,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_OTHER


def test_reply_to_other_when_bob_id_unknown_is_directed_to_other() -> None:
    # Identity Боба не резолвнута: reply на кого-то — мы не можем сказать, что это Боб,
    # значит это другой человек → DIRECTED_TO_OTHER (mention всё равно работал бы).
    result = classify_addressivity(
        text="ну да",
        mentions_bob=False,
        reply_to_sender_id=_OTHER_ID,
        bob_user_id=None,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_OTHER


# --- AMBIENT -----------------------------------------------------------------


def test_no_signal_is_ambient() -> None:
    # Ни reply, ни mention, ни имя-обращение → общее/риторическое.
    result = classify_addressivity(
        text="вот это денёк",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=True,
    )
    assert result is Addressivity.AMBIENT


def test_empty_text_is_ambient() -> None:
    result = classify_addressivity(
        text=None,
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.AMBIENT


def test_mention_overrides_empty_text() -> None:
    # mention не зависит от текста.
    result = classify_addressivity(
        text=None,
        mentions_bob=True,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


# --- others_present ----------------------------------------------------------


def test_others_present_true_when_history_has_a_different_sender() -> None:
    history = ["Ada: привет\nbob: здравствуй", "Гость: эй\nbob: о, привет"]
    assert others_present(history, current_sender_name="Ada") is True


def test_others_present_false_in_one_to_one() -> None:
    # Все недавние реплики — от текущего собеседника → 1:1.
    history = ["Ada: привет\nbob: здравствуй", "Ada: как дела\nbob: норм"]
    assert others_present(history, current_sender_name="Ada") is False


def test_others_present_false_on_empty_history() -> None:
    assert others_present([], current_sender_name="Ada") is False


def test_others_present_ignores_bob_turns() -> None:
    # «bob:» — не сторонний собеседник.
    history = ["Ada: привет\nbob: здравствуй"]
    assert others_present(history, current_sender_name="Ada") is False
