# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Дверь генерации: чем является вывод одного вида работы LLM (BOB-096, срез 3).

Дефект, ради которого понятие двери заведено: запрет отыгрывать GUPPI был приклеен
к ОДНОЙ двери — разговорному ходу, — а двери, чей вывод ложится в память (рефлексия,
переоценка, консолидация, проактивная реплика, work_journal, ``extract_facts``),
канона не видели и производили будущие few-shot по нарушению канона. Механизм
отравления — BOB-074: подражание собственной истории.

Здесь пинается САМО понятие: у каждой двери названы независимые факты о выводе —
«это голос Боба» и «вывод переживает ход», — и ни один вид работы не остаётся без
ответа на них. Незнакомая дверь считается голосом, который остаётся (fail-closed):
молчаливое выпадение из-под канона — ровно тот дефект, который здесь чинится.
"""

from __future__ import annotations

from enum import Enum
from typing import cast

import pytest

from bob.application.router.generation_door import (
    UNCLASSIFIED_DOOR,
    GenerationDoor,
    TaskType,
    door_for,
)

# Двери из карты разведки, чей вывод ложится в память от лица Боба. Автобиография
# (``memory/self_action.py``) в список не входит: у неё нет модели — это детерминированный
# шаблон, и канон достигается там конструкцией, а не промптом.
_MEMORY_WRITING = (
    TaskType.REFLECT,  # рефлексия + переоценка + дайджест консолидации
    TaskType.REPLY_TO_USER,  # разговорный ход + проактивная реплика
    TaskType.WORK_JOURNAL,
    TaskType.EXTRACT_FACTS,
    # 🔴 Обе двери добавлены сверкой разметки с ФАКТИЧЕСКИМ вызывающим (BOB-096.8):
    # тема очарования ложится в ``fascination_store`` и потом вплетается в реплики, а
    # прочтение реакции ложится в эпизод «X отреагировал … — <прочтение>» и в стор
    # заметных реакций. Обе раньше числились служебными «по предположению».
    TaskType.FASCINATION_PICK,
    TaskType.REACTION_JUDGE,
)

# Служебные двери: вердикт/метка/классификация, расходуемые в этом же ходе.
_SERVICE = (
    TaskType.SENTIMENT,
    TaskType.INNER_MONOLOGUE,
    TaskType.RESPONSE_JUDGE,
    TaskType.PRIVILEGE_JUDGE,
    TaskType.VOLATILITY_JUDGE,
    TaskType.STALENESS_JUDGE,
    TaskType.DISCLOSURE_CONSENT,
    TaskType.CODING_INTENT,
    TaskType.WORK_TALK,
    TaskType.ROOM_READ,
)


def test_every_kind_of_llm_work_is_classified() -> None:
    # 🔴 Гард понятия: новый вид работы обязан назвать, чем является его вывод. Пока
    # ответа нет, дверь не может «просто появиться» — здесь краснеет.
    unclassified = [task for task in TaskType if door_for(task) is UNCLASSIFIED_DOOR]

    assert unclassified == []


@pytest.mark.parametrize("task", _MEMORY_WRITING)
def test_a_door_whose_output_is_kept_needs_the_voice_canon(task: TaskType) -> None:
    door = door_for(task)

    assert door.output_is_kept is True
    assert door.needs_voice_canon is True


@pytest.mark.parametrize("task", _SERVICE)
def test_a_service_door_needs_no_canon(task: TaskType) -> None:
    door = door_for(task)

    assert door.speaks_as_bob is False
    assert door.output_is_kept is False
    assert door.needs_voice_canon is False


def test_bobs_voice_alone_is_enough_to_need_the_canon() -> None:
    # Свойства независимы: промежуточная строчка «секунду, гляну» нигде не сохраняется и
    # при сбое молча пропадает — но она печатается в чате как реплика Боба, и «GUPPI
    # сейчас глянет» в ней запрещено ровно так же.
    door = door_for(TaskType.INTERIM_LINE)

    assert door.speaks_as_bob is True
    assert door.output_is_kept is False
    assert door.needs_voice_canon is True


def test_a_record_keeping_door_needs_the_canon_without_speaking_as_bob() -> None:
    # ``extract_facts`` голосом Боба не говорит — но его выжимка ложится в semantic_memory
    # и возвращается в ход через припоминание. Одного этого хватает.
    door = door_for(TaskType.EXTRACT_FACTS)

    assert door.speaks_as_bob is False
    assert door.output_is_kept is True
    assert door.needs_voice_canon is True


def test_the_voice_that_stays_is_expressible_for_the_understudy_verdict() -> None:
    # 🔴 Понятие для среза 4: «дублёр недопустим» = голос Боба, который ОСТАЁТСЯ. Пара
    # свойств воспроизводит решение owner'а (BOB-087.E-M1) без ``task_type is
    # REPLY_TO_USER``: разговорный ход и рефлексия — да, промежуточная строчка — нет.
    def voice_that_stays(task: TaskType) -> bool:
        door = door_for(task)
        return door.speaks_as_bob and door.output_is_kept

    assert voice_that_stays(TaskType.REPLY_TO_USER) is True
    assert voice_that_stays(TaskType.REFLECT) is True
    assert voice_that_stays(TaskType.WORK_JOURNAL) is True
    assert voice_that_stays(TaskType.DETECT_PATTERNS) is True
    assert voice_that_stays(TaskType.INTERIM_LINE) is False
    assert voice_that_stays(TaskType.EXTRACT_FACTS) is False
    assert voice_that_stays(TaskType.RESPONSE_JUDGE) is False


def test_the_fascination_pick_is_a_voice_that_stays() -> None:
    """🔴 Ревью BOB-096 (MAJOR-2): дверь была размечена по НЕВЕРНОМУ факту.

    Выбор увлечения ходил дверью «внутренний монолог», у которой в реестре написано
    «нигде не публикуется и не сохраняется». Его уже сохраняли: ответ модели становится
    ``Fascination.topic``, ложится в SQLite и неделями вплетается в контекст ответа — то
    есть Боб ГОВОРИТ им о себе. Дверь разведена и размечена по факту.
    """
    door = door_for(TaskType.FASCINATION_PICK)

    assert door.speaks_as_bob is True
    assert door.output_is_kept is True
    # Ответ разбирает код (короткая именная фраза, первая строка), а не читает человек:
    # полная проза о речи сбила бы 0.5b-модель с формата.
    assert door.answers_in_machine_format is True


def test_the_inner_monologue_is_service_only_now_that_the_pick_moved_out() -> None:
    # У оставшихся двух вызывающих (шаг настроения и гейт проактивности) вывод правда
    # расходуется в этом же ходе: мысль превращается в дельту настроения, а вердикт
    # гейта — в решение «заговаривать ли», и ни то ни другое никуда не ложится.
    door = door_for(TaskType.INNER_MONOLOGUE)

    assert door.speaks_as_bob is False
    assert door.output_is_kept is False


def test_the_reaction_reading_is_kept_because_it_lands_in_memory() -> None:
    # Второй случай той же сверки: прочтение реакции («он одобрил») попадает в эпизод
    # «Лиля отреагировала 👍 на моё «…» — <прочтение>» и в стор заметных реакций, откуда
    # возвращается припоминанием. Голосом Боба дверь не говорит (её ответ разбирает код),
    # но одного «вывод остаётся» достаточно — как у выжимки фактов.
    door = door_for(TaskType.REACTION_JUDGE)

    assert door.speaks_as_bob is False
    assert door.output_is_kept is True
    assert door.needs_voice_canon is True
    assert door.answers_in_machine_format is True


def test_a_machine_format_door_is_marked_as_such() -> None:
    # У двери, отвечающей JSON'ом, канон обязан быть в форме, не зовущей в прозу:
    # полный запрет о голосе («вызови инструмент… говори от себя») сломал бы контракт.
    assert door_for(TaskType.EXTRACT_FACTS).answers_in_machine_format is True
    assert door_for(TaskType.DETECT_PATTERNS).answers_in_machine_format is True
    assert door_for(TaskType.GENESIS).answers_in_machine_format is True
    assert door_for(TaskType.REFLECT).answers_in_machine_format is False


def test_an_unknown_door_is_treated_as_a_voice_that_stays() -> None:
    # 🔴 Fail-closed, как у следа материала (BOB-090.B-fix2): неизвестная дверь получает
    # канон, а не тишину. Тихо выпасть из-под запрета — это и есть чинимый дефект.
    _Stranger = Enum("_Stranger", "MYSTERY")  # noqa: N806 — имя класса, а не переменной

    door = door_for(cast("TaskType", _Stranger.MYSTERY))

    assert door is UNCLASSIFIED_DOOR
    assert door.speaks_as_bob is True
    assert door.output_is_kept is True
    assert door.needs_voice_canon is True


def test_a_door_with_neither_property_needs_nothing() -> None:
    door = GenerationDoor(speaks_as_bob=False, output_is_kept=False)

    assert door.needs_voice_canon is False
