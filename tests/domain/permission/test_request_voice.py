# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Голос Боба на запросе разрешения — чистое ядро (BOB-090.E).

Живой симптом (строка из таблицы ``permission_request`` живой базы): owner получил
«Вова, Norman просит **Requesting details of private conversations with another user** —
разрешить?». Английская служебная строка от классификатора внутри русской фразы: судья
возвращал ``what``, и он подставлялся в шаблон дословно. Звучит как форма на подпись, а
не как Боб.

Здесь пинуется реплика, которой это лечится: Боб СВОИМИ словами говорит owner'у, кто
просит, чего именно (словами САМОГО просителя, а не классификатора) и почему он
спрашивает. Вердикт судьи (``needs_permission`` / ``kind`` / его ``what``) наружу не
выходит вовсе — ``kind`` только ВЫБИРАЕТ, какими словами Боб объясняет причину.
"""

from __future__ import annotations

import re

from bob.social.permission.privilege import PRIVILEGE_KINDS
from bob.social.permission.request_voice import owner_permission_notice, requester_ack

# Английская фраза судьи из живой базы — ровно то, что просочилось наружу.
_LEAKED_WHAT = "Requesting details of private conversations with another user"

_ASK = "расскажи, о чём вы с Вовой говорили вчера"


def _notice(
    *,
    kind: str = "owner_data",
    owner_name: str = "Вова",
    requester_name: str = "Норман",
    request_text: str = _ASK,
) -> str:
    return owner_permission_notice(
        owner_name=owner_name,
        requester_name=requester_name,
        kind=kind,
        request_text=request_text,
    )


# --- Кто просит, чего именно, почему Боб спрашивает ----------------------------


def test_notice_names_the_owner_the_requester_and_quotes_the_ask() -> None:
    notice = _notice()

    # Owner — упоминанием (заземлит его ростер, см. ground_mentions среза B).
    assert notice.startswith("@Вова,")
    assert "Норман" in notice
    # «Чего именно» — словами самого просителя, а не классификатора.
    assert f"«{_ASK}»" in notice


def test_notice_ends_with_a_question_the_owner_can_answer() -> None:
    # Owner отвечает «да» / «нет» / «авторизуй» — реплика обязана быть вопросом.
    assert _notice().rstrip().endswith("?")


def test_notice_speaks_the_project_language_without_service_english() -> None:
    # Мера «живости» среза D: реплика целиком на языке проекта. Латиница в шаблоне —
    # это и есть тот самый вердикт классификатора, просочившийся наружу.
    assert re.search(r"[A-Za-z]", _notice()) is None


def test_the_judges_own_phrase_never_reaches_the_owner() -> None:
    # 🔴 Регресс на живой дефект: билдер физически не принимает ``what``, поэтому фраза
    # судьи не может оказаться в реплике — даже если она осталась в записи запроса.
    notice = _notice(request_text="what do you two talk about?")
    assert _LEAKED_WHAT not in notice


def test_internal_verdict_tokens_never_leak_into_the_notice() -> None:
    # Вердикт — машинное решение: ни его поля, ни имена видов наружу не идут.
    for kind in ("tool", "internal", "owner_data"):
        notice = _notice(kind=kind)
        assert "needs_permission" not in notice
        assert kind not in notice


# --- Причина зависит от вида привилегии (таблица истинности) -------------------


def test_each_kind_gets_its_own_reason_in_bobs_words() -> None:
    tool = _notice(kind="tool")
    internal = _notice(kind="internal")
    owner_data = _notice(kind="owner_data")

    # Три разных повода — три разных объяснения, иначе «почему спрашиваю» пустой звук.
    assert len({tool, internal, owner_data}) == 3
    # Инструмент — «сделать за него»; внутрянка — про самого Боба; owner_data — про Вову.
    assert "сделать" in tool
    assert "внутренн" in internal
    assert "личн" in owner_data


def test_every_kind_the_judge_may_return_has_its_own_wording() -> None:
    # Дрейф-гард: виды судьи и виды голоса — один список. Появится новый вид у судьи, а
    # объяснения к нему не будет — реплика молча свалится в общий случай, и owner
    # перестанет понимать, о чём его спрашивают.
    fallback = _notice(kind="ни на что не похоже")
    for kind in PRIVILEGE_KINDS:
        assert _notice(kind=kind) != fallback


def test_unknown_kind_still_asks_instead_of_breaking() -> None:
    # Парсер судьи вид валидирует, но ядро обязано быть тотальным: неизвестный вид —
    # это по-прежнему просьба к owner'у, а не исключение и не пустая строка.
    notice = _notice(kind="что-то новое")

    assert "Норман" in notice
    assert notice.rstrip().endswith("?")


def test_kind_is_read_case_and_space_insensitively() -> None:
    assert _notice(kind="  TOOL  ") == _notice(kind="tool")


# --- Слова просителя цитируются бережно ---------------------------------------


def test_a_multiline_ask_is_flattened_into_one_quoted_line() -> None:
    notice = _notice(request_text="покажи\n\nзадачи   проекта")

    assert "«покажи задачи проекта»" in notice
    assert "\n" not in notice


def test_a_long_ask_is_capped_so_the_notice_stays_a_message() -> None:
    # Подрез — ровно по границе (199 символов + многоточие = 200): вопрос «можно?» не
    # должен тонуть в чужой простыне, а сдвиг границы обязан быть виден.
    notice = _notice(request_text="я" * 300)

    assert f"«{'я' * 199}…»" in notice
    assert "я" * 201 not in notice


def test_an_ask_that_fits_is_quoted_whole() -> None:
    # Ровно по границе — цитата целиком, без многоточия: подрезаем только то, что длиннее.
    notice = _notice(request_text="я" * 200)

    assert f"«{'я' * 200}»" in notice
    assert "…" not in notice


def test_an_empty_ask_leaves_no_dangling_quotes() -> None:
    # Пустая просьба не цитируется вовсе — и на её месте не появляется НИЧЕГО: фраза
    # смыкается ровно так, как звучала бы без цитаты.
    notice = _notice(request_text="   ")

    assert "«" not in notice
    assert "»" not in notice
    assert notice == _notice(request_text=_ASK).replace(f": «{_ASK}»", "")
    assert notice.rstrip().endswith("?")


def test_a_nameless_requester_is_not_given_an_invented_name() -> None:
    # Имя не выдумывается (тот же принцип, что и с тегами в срезе B) — Боб честно
    # говорит, что просит кто-то из чата.
    notice = _notice(requester_name="  ")

    assert "@Вова," in notice
    assert notice.rstrip().endswith("?")


def test_the_notice_is_deterministic() -> None:
    assert _notice() == _notice()


# --- Лёгкий ack просителю ------------------------------------------------------


def test_requester_ack_is_the_light_promise_to_ask_the_owner() -> None:
    # Реплика просителю не менялась (фикс треда B5 держится за канал, не за текст).
    assert requester_ack() == "Секунду, спрошу Вову."
