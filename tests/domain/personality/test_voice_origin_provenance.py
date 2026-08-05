# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Провенанс «где это было» — Боб ВИДИТ источник припомненного (BOB-090.C1).

Живой дефект, ради которого срез: эпизод 3092 — Боб уверенно заявил «я объяснил
Норману в группе пару сообщений назад», хотя объяснял в ЛИЧКЕ. Он не соврал: место
разговора в промпт не попадало вовсе, и он его домыслил.

Здесь два уровня одного поведения:

* **ядро** — :func:`~bob.personality.voice.recalled_origin_directive`: чистая функция,
  которая по ``visibility`` припомненного (та самая, что уже пишется в ``episodic_log``
  с BOB-082.1) строит живую пометку «это было наедине / при всех / и там, и там».
* **проводка** — та же строка, увиденная на ГРАНИЦЕ: в системном промпте, который
  реальный :class:`~bob.personality.usecases.voice_composer.VoiceComposer` отдаёт
  модели. Флаг ``origin_provenance`` выключен по умолчанию → промпт байт-в-байт
  прежний (доказывается равенством строк, а не «похоже»).

🔴 Провенанс — СИГНАЛ ДЛЯ СУЖДЕНИЯ, а не фильтр: сквозная память (BOB-082) остаётся,
из выдачи не вырезается ничего. Это проверяется на границе — ассемблер контекста
получает ТУ ЖЕ последовательность, включая ``owner_private``.
"""

from __future__ import annotations

import asyncio

from bob.personality.expression import Verbosity
from bob.personality.voice import (
    _VISIBILITY_OWNER_PRIVATE,
    _VISIBILITY_PUBLIC,
    recalled_origin_directive,
    recalled_work_directive,
)
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE, VISIBILITY_PUBLIC
from tests.acceptance.formatting_harness import compose_turn, composed_prompt

_IN_DM = {"content": "мы обсуждали ограниченный доступ", "visibility": "owner_private"}
_IN_ROOM = {"content": "Норман спросил про доступ", "visibility": "public"}
_LEGACY = {"content": "старая запись без источника"}


# --- Ядро: классификация источника ------------------------------------------


def test_origin_marker_mirror_matches_social_domain_source_of_truth() -> None:
    # DRIFT-GUARD: voice.py держит документированный МИРРОР меток видимости, чтобы
    # чистый personality-домен не импортировал social (как _SELF_ACTION_CATEGORY
    # зеркалит memory). Если источник истины уедет — провенанс молча перестанет
    # срабатывать на реальных эпизодах, и промах вернётся. Тест падает громко.
    assert _VISIBILITY_OWNER_PRIVATE == VISIBILITY_OWNER_PRIVATE
    assert _VISIBILITY_PUBLIC == VISIBILITY_PUBLIC


def test_only_private_recall_says_it_was_said_one_on_one() -> None:
    line = recalled_origin_directive([_IN_DM])

    folded = line.casefold()
    assert "личк" in folded  # «в личке» — так и говори
    assert "общем чате" in folded  # …и не приписывай это общему чату


def test_only_public_recall_says_it_was_said_in_the_room() -> None:
    line = recalled_origin_directive([_IN_ROOM])

    folded = line.casefold()
    assert "общем чате" in folded
    assert "при всех" in folded


def test_mixed_recall_warns_against_confusing_the_two_places() -> None:
    line = recalled_origin_directive([_IN_DM, _IN_ROOM])

    folded = line.casefold()
    assert "личк" in folded
    assert "общем чате" in folded
    # Прямая защита от эпизода 3092: наугад место не называть.
    assert "наугад" in folded


def test_the_three_lines_are_distinct() -> None:
    private = recalled_origin_directive([_IN_DM])
    room = recalled_origin_directive([_IN_ROOM])
    mixed = recalled_origin_directive([_IN_DM, _IN_ROOM])

    assert len({private, room, mixed}) == 3


def test_empty_recall_has_no_line() -> None:
    assert recalled_origin_directive([]) == ""


def test_legacy_memory_without_visibility_has_no_line() -> None:
    # Старая запись без метки — источник НЕИЗВЕСТЕН. Честнее промолчать о месте,
    # чем выдать «NULL = публично» гейта разглашения за «сказано при всех».
    assert recalled_origin_directive([_LEGACY]) == ""


def test_unrecognised_visibility_value_has_no_line() -> None:
    assert recalled_origin_directive([{"content": "x", "visibility": "moon"}]) == ""


def test_non_string_visibility_is_ignored() -> None:
    assert recalled_origin_directive([{"content": "x", "visibility": 1}]) == ""


def test_visibility_match_tolerates_case_and_padding() -> None:
    padded = [{"content": "x", "visibility": "  Owner_Private "}]

    assert recalled_origin_directive(padded) == recalled_origin_directive([_IN_DM])


def test_legacy_item_does_not_dilute_a_known_origin() -> None:
    # Смесь «личка + запись без метки» — это всё ещё личка, а не «и там, и там»:
    # неизвестный источник не выдаётся за общий чат.
    assert recalled_origin_directive([_IN_DM, _LEGACY]) == recalled_origin_directive(
        [_IN_DM]
    )


def test_directive_is_voice_not_a_rule_list() -> None:
    for line in (
        recalled_origin_directive([_IN_DM]),
        recalled_origin_directive([_IN_ROOM]),
        recalled_origin_directive([_IN_DM, _IN_ROOM]),
    ):
        assert "•" not in line
        assert "- " not in line


def test_core_never_touches_the_recalled_set() -> None:
    # 🔴 Не силосить: источник — сигнал для суждения, а не фильтр. Ядро читает и
    # ничего не выкидывает и не переставляет.
    recalled = [_IN_DM, _IN_ROOM, _LEGACY]
    snapshot = list(recalled)

    recalled_origin_directive(recalled)

    assert recalled == snapshot


# --- Проводка: та же строка на границе (системный промпт) --------------------


def test_directive_reaches_the_prompt_when_the_flag_is_on() -> None:
    prompt = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[_IN_DM], origin_provenance=True)
    )

    assert recalled_origin_directive([_IN_DM]) in prompt


def test_flag_off_is_the_default_and_the_prompt_never_mentions_the_source() -> None:
    prompt = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=[_IN_DM]))

    assert recalled_origin_directive([_IN_DM]) not in prompt


def test_flag_off_prompt_is_byte_identical_to_the_pre_feature_prompt() -> None:
    # Байт-в-байт доказывается РАВЕНСТВОМ: с выключенным флагом промпт не зависит
    # от того, несёт ли припомненное метку источника вообще.
    with_visibility = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[_IN_DM, _IN_ROOM])
    )
    without_visibility = asyncio.run(
        composed_prompt(
            Verbosity.NORMAL,
            recalled=[{"content": _IN_DM["content"]}, {"content": _IN_ROOM["content"]}],
        )
    )

    assert with_visibility == without_visibility


def test_flag_on_adds_exactly_one_line_and_nothing_else() -> None:
    # Второе доказательство байт-в-байт: ON-промпт минус ровно одна вставленная
    # строка совпадает с OFF-промптом посимвольно.
    recalled = [_IN_DM, _IN_ROOM]
    off = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=recalled))
    on = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=recalled, origin_provenance=True)
    )

    line = recalled_origin_directive(recalled)
    assert on != off
    assert on.replace(f"\n{line}", "", 1) == off


def test_flag_on_with_legacy_recall_keeps_the_prompt_byte_identical() -> None:
    off = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=[_LEGACY]))
    on = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[_LEGACY], origin_provenance=True)
    )

    assert on == off


def test_recall_is_not_siloed_when_the_flag_is_on() -> None:
    # 🔴 Сквозная память (BOB-082): приватный эпизод по-прежнему доходит до
    # ассемблера контекста — Боб один разум, провенанс ничего не вырезает.
    recalled = [_IN_DM, _IN_ROOM, _LEGACY]

    turn = asyncio.run(
        compose_turn(Verbosity.NORMAL, recalled=recalled, origin_provenance=True)
    )

    assert list(turn.context_recalled) == recalled


def test_origin_axis_is_orthogonal_to_the_work_register_axis() -> None:
    # Ось «где сказано» не подменяет ось регистра «про что» (BOB-087.C):
    # приватный WORK-эпизод поднимает ОБЕ директивы разом.
    work_in_dm = {
        "content": "я попросил GUPPI поднять лимит",
        "category": "work",
        "visibility": "owner_private",
    }
    prompt = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[work_in_dm], origin_provenance=True)
    )

    assert recalled_work_directive() in prompt
    assert recalled_origin_directive([work_in_dm]) in prompt


# --- BOB-090.C2: точный адрес — метаданные хранения, а НЕ материал промпта ----
# У записи адреса (origin_chat_id / origin_topic_id) флага нет, поэтому «байт-в-байт»
# доказывается равенством и здесь, на границе: припомненное с адресом даёт ровно тот же
# системный промпт, что и без адреса. Точный чат/топик — сигнал для будущей АДРЕСАЦИИ
# (срез B), Боб им не говорит.

_IN_ROOM_ADDRESSED = {
    "content": "Норман спросил про доступ",
    "visibility": "public",
    "origin_chat_id": -1004372947307,
    "origin_topic_id": 32,
}


def test_exact_address_never_changes_the_prompt() -> None:
    with_address = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[_IN_ROOM_ADDRESSED])
    )
    without_address = asyncio.run(composed_prompt(Verbosity.NORMAL, recalled=[_IN_ROOM]))

    assert with_address == without_address


def test_exact_address_never_changes_the_prompt_with_provenance_on() -> None:
    # И с включённым провенансом тоже: грубая пометка «где» строится по visibility,
    # точный адрес в текст не подмешивается ни одним символом.
    with_address = asyncio.run(
        composed_prompt(
            Verbosity.NORMAL, recalled=[_IN_ROOM_ADDRESSED], origin_provenance=True
        )
    )
    without_address = asyncio.run(
        composed_prompt(Verbosity.NORMAL, recalled=[_IN_ROOM], origin_provenance=True)
    )

    assert with_address == without_address
