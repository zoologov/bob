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

from bob.conversation.addressivity import (
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


def test_others_present_skips_entries_without_a_sender_label() -> None:
    # Запись без разделителя «<sender>: » (битая/системная строка) пропускается,
    # а не считается сторонним участником: тред остаётся 1:1.
    history = ["системное уведомление без метки", "Ada: привет\nbob: здравствуй"]
    assert others_present(history, current_sender_name="Ada") is False


def test_others_present_true_when_label_missing_among_others() -> None:
    # Битая запись пропускается, но реальный сторонний участник всё равно ловится.
    history = ["битая строка", "Гость: эй\nbob: о, привет"]
    assert others_present(history, current_sender_name="Ada") is True


def test_others_present_true_without_current_name_when_any_other_speaks() -> None:
    # Без имени текущего собеседника любая сторонняя (не-Боб) реплика читается как
    # присутствие другого: мы не можем сопоставить метку → считаем тред не-1:1.
    history = ["Ada: привет\nbob: здравствуй"]
    assert others_present(history, current_sender_name=None) is True


def test_others_present_false_without_current_name_when_history_is_unlabelled() -> None:
    # Без имени текущего собеседника история без меток отправителя (только текст без
    # «<sender>: ») — не присутствие другого: метку не из чего считать.
    history = ["просто строка", "ещё одна без метки"]
    assert others_present(history, current_sender_name=None) is False


def test_name_address_with_colon_is_directed_to_bob() -> None:
    # Двоеточие сразу за именем читается как обращение («Боб: …»).
    for text in ("Боб: слушай", "Bob: hey", "боб:"):
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=False,
        )
        assert result is Addressivity.DIRECTED_TO_BOB, text


def test_name_with_immediate_dash_is_ambient_not_directed() -> None:
    # 🔴 BOB-069.6 (fix major): тире/длинное тире ВПЛОТНУЮ за именем — это 3-е лицо
    # или композит («Боб-строитель», «боб-конструктор», «Боб—робот» = «Bob is a
    # robot»), а НЕ обращение. Настоящий оклик через тире идёт С ПРОБЕЛОМ («эй Боб -
    # ты тут?»), где справа от имени пробел, а не тире вплотную. Значит тире-вплотную
    # даёт ТОЛЬКО ложь → убрано из терминаторов-обращения.
    for text in ("Боб-строитель", "боб-конструктор", "Боб—робот", "Bob-builder"):
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=False,
        )
        assert result is Addressivity.AMBIENT, text


def test_name_address_with_leading_whitespace_is_directed_to_bob() -> None:
    # Ведущие пробелы перед обращением не мешают распознаванию («  Боб, …»).
    result = classify_addressivity(
        text="   Боб, ты тут?",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_name_only_bob_without_separator_is_ambient() -> None:
    # Ровно «Боб» без разделителя за именем — не обращение (нет запятой/двоеточия).
    result = classify_addressivity(
        text="Боб",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.AMBIENT


def test_mid_vocative_is_directed_to_bob() -> None:
    # BOB-069.A: вокатив «Боб» в ЛЮБОЙ позиции — обращение. Левая граница слова
    # (разделитель/пробел) + терминатор-обращения (разделитель/«!»/«?»/конец строки
    # при контексте слева) сразу за именем.
    engaging = (
        "Боб, ты тут?",  # старт + запятая
        "Кстати, Боб, расскажи",  # середина, запятая справа
        "…, Боб?",  # трейлинг-вокатив + «?»
        "эй Боб!",  # пробел слева + «!»
        "боб:",  # старт + двоеточие
        "ну что, Боб",  # трейлинг-вокатив, конец строки, контекст слева
        "привет, Боб",  # трейлинг-вокатив в конце
        "Боб!",  # имя + «!»
        "Боб?",  # имя + «?»
        "скажи, БОБ, как дела",  # верхний регистр в середине
        "hey Bob, listen",  # латиница в середине
        "так, Боб, и ещё, Боб, вот",  # несколько запятых-вокативов
    )
    for text in engaging:
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=False,
        )
        assert result is Addressivity.DIRECTED_TO_BOB, text


def test_name_mentioned_not_vocative_is_ambient() -> None:
    # 🔴 Guard: имя присутствует, но это НЕ оклик (падеж / имя-подлежащее /
    # середина слова) → остаётся AMBIENT, а не ложное срабатывание.
    ambient = (
        "Боб молодец",  # за именем пробел+слово, а не терминатор
        "расскажу Бобу про X",  # дательный падеж
        "думаю про Боба",  # винительный падеж
        "поговорил с Бобом",  # творительный падеж
        "Бобслей — это спорт",  # имя-подслово в начале
        "работает робобот",  # «боб» внутри слова
        "это пробоб какой-то",  # буква слева от «боб»
    )
    for text in ambient:
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=False,
        )
        assert result is Addressivity.AMBIENT, text


def test_first_vocative_wins_over_a_later_non_vocative_occurrence() -> None:
    # 🔴 BOB-069.A доукрепление (mutation): сканирование идёт СЛЕВА-направо и берёт
    # ПЕРВОЕ вхождение-вокатив. «Боб, а вот бобслей» — первое «Боб,» это оклик, а
    # последнее «боб» (в «бобслей») — нет. Детектор обязан поймать первое, а не
    # смотреть только на последнее вхождение имени.
    result = classify_addressivity(
        text="Боб, а вот бобслей — тема",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_middle_vocative_between_non_vocative_occurrences_is_directed() -> None:
    # 🔴 BOB-069.A доукрепление (mutation): вокатив в СЕРЕДИНЕ между двумя
    # не-вокативами — «бобром, Боб, бобслей». Первое «боб» (бобром) и последнее «боб»
    # (бобслей) — не оклик, но среднее «Боб,» — да. Перебор не должен перепрыгивать
    # средние вхождения.
    result = classify_addressivity(
        text="бобром, Боб, бобслей",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_trailing_vocative_with_single_separator_prefix_is_directed() -> None:
    # 🔴 BOB-069.A доукрепление (mutation, граница start==1): имя в самом конце строки
    # с ЕДИНСТВЕННЫМ контекст-символом слева (разделитель-обращение вплотную) читается
    # как трейлинг-вокатив. Одного левого контекст-символа достаточно (start > 0).
    result = classify_addressivity(
        text=",Боб",
        mentions_bob=False,
        reply_to_sender_id=None,
        bob_user_id=_BOB_ID,
        others_present=False,
    )
    assert result is Addressivity.DIRECTED_TO_BOB


def test_lone_bob_with_or_without_leading_whitespace_is_ambient() -> None:
    # 🔴 BOB-069.6 (fix minor, был флаг ревью .4): голое имя — с ВЕДУЩИМ пробелом
    # (« Боб») или без («Боб») — одинаково AMBIENT. Ведущий пробел даёт start>0, но
    # слева НЕТ реального address-контекста (только whitespace), поэтому это не
    # трейлинг-вокатив «…, Боб», а то же самое одинокое имя. Асимметрия «start>0»
    # устранена: EOL-вокатив требует непробельный контекст слева.
    for text in ("   Боб", "Боб"):
        result = classify_addressivity(
            text=text,
            mentions_bob=False,
            reply_to_sender_id=None,
            bob_user_id=_BOB_ID,
            others_present=False,
        )
        assert result is Addressivity.AMBIENT, text


def test_reply_to_bob_needs_resolved_identity() -> None:
    # Реплай на сообщение с тем же id, что у «Боба», но identity не резолвнута
    # (bob_user_id=None) → не можем утверждать, что это Боб → DIRECTED_TO_OTHER.
    result = classify_addressivity(
        text="ага",
        mentions_bob=False,
        reply_to_sender_id=_BOB_ID,
        bob_user_id=None,
        others_present=True,
    )
    assert result is Addressivity.DIRECTED_TO_OTHER
