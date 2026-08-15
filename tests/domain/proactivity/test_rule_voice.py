# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Голос Боба, когда он предлагает поправить САМОГО СЕБЯ (BOB-096 срез 5).

Живой симптом (owner, 12 августа 2026): «Заметил за собой: Боб замечает, что его
поведение часто повторяется**..** Предлагаю: **.** Включить? (/rule approve rule-…)».
Три шва в одной фразе: сырой вывод детектора подставлен дословно (и потому Боб говорит
о себе в ТРЕТЬЕМ лице), пустой слот дал двойную точку, а идентификатор правила оказался
внутри реплики. Приговор owner'а: «выглядит очень скриптовано, а не человечно».

Здесь пинуется лечение — то же разделение ролей, что в
:mod:`bob.social.permission.request_voice`: вердикт детектора (рычаг + величина)
остаётся ВНУТРИ и лишь ВЫБИРАЕТ, какими словами Боб говорит о себе; его сырой текст в
реплику не попадает — билдер речи его физически не принимает.
"""

from __future__ import annotations

import inspect
import re
from typing import cast

from bob.proactivity.rule_voice import proposal_message, proposal_speech
from bob.proactivity.self_improvement import Lever

# Ровно тот мусор, что уехал owner'у: третье лицо о себе + пустая поправка.
_LEAKED_OBSERVATION = "Боб замечает, что его поведение часто повторяется"
_RULE_ID = "rule-20260812190500-0"

# Величины из реально достижимого диапазона (потолок конфига сегодня 0.3).
_SMALL = 0.05
_NOTICEABLE = 0.25


def _speech(*, lever: Lever = Lever.TONE, magnitude: float = _SMALL) -> str:
    return proposal_speech(lever=lever, magnitude=magnitude)


def _message(
    *,
    lever: Lever = Lever.TONE,
    magnitude: float = _SMALL,
    rule_id: str = _RULE_ID,
) -> str:
    return proposal_message(lever=lever, magnitude=magnitude, rule_id=rule_id)


def _every_speech() -> list[str]:
    return [
        _speech(lever=lever, magnitude=magnitude)
        for lever in Lever
        for magnitude in (0.0, _SMALL, _NOTICEABLE, 0.9)
    ]


# --- Боб говорит о себе сам, от первого лица -----------------------------------


def test_bob_speaks_about_himself_in_the_first_person() -> None:
    # 🔴 Сердце жалобы: в собственной реплике Боб говорил о себе «Боб замечает…».
    for speech in _every_speech():
        assert "Боб" not in speech
        assert "его поведение" not in speech
        assert "хочу" in speech.casefold()


def test_the_speech_ends_with_a_question_the_owner_can_answer() -> None:
    for speech in _every_speech():
        assert speech.rstrip().endswith("?")


def test_the_speech_is_not_a_form_with_headed_fields() -> None:
    # «Заметил за собой:» читалось как заголовок графы, а не как речь. Двоеточия в
    # реплике нет вовсе — значит нет и графы, в которую подставляют значение.
    for speech in _every_speech():
        assert ":" not in speech


def test_the_speech_carries_no_service_latin() -> None:
    # Мера «живости» (та же, что у request_voice): реплика целиком на языке проекта.
    # Латиница здесь могла появиться только из машинного вердикта — имени рычага,
    # идентификатора правила или команды.
    for speech in _every_speech():
        assert re.search(r"[A-Za-z]", speech) is None


def test_no_lever_name_leaks_into_the_speech() -> None:
    for lever in Lever:
        speech = _speech(lever=lever)
        assert lever.value not in speech
        assert lever.name not in speech


# --- Сырой текст детектора не может попасть в реплику --------------------------


def test_the_detector_text_is_not_accepted_by_the_voice_at_all() -> None:
    # 🔴 Регресс на живой дефект по образцу request_voice: билдер физически не
    # принимает ни наблюдение, ни поправку, поэтому текст модели не может стать телом
    # фразы — ни сейчас, ни при неаккуратной доработке вызывающего кода.
    for builder in (proposal_speech, proposal_message):
        params = set(inspect.signature(builder).parameters)
        assert "observation" not in params
        assert "adjustment" not in params
        assert "rule" not in params
        assert "evidence" not in params


def test_the_leaked_observation_cannot_appear_in_the_message() -> None:
    assert _LEAKED_OBSERVATION not in _message()


# --- Пустых слотов и двойной пунктуации нет ПО КОНСТРУКЦИИ ---------------------


def test_no_empty_slot_artefacts_in_any_phrase() -> None:
    # Двойная точка в живом сообщении родилась из пустого слота. Слотов больше нет —
    # фраза собрана из готовых кусков, поэтому склейка не может дать ни «..», ни
    # висящего пробела перед знаком.
    for speech in _every_speech():
        assert ".." not in speech
        assert " ." not in speech
        assert " ?" not in speech
        assert " ," not in speech
        assert "  " not in speech
        assert speech == speech.strip()


def test_a_strange_magnitude_still_reads_as_a_sentence() -> None:
    # Вырожденное предложение не рождается (срез 2), но форма обязана держаться и на
    # странном входе: ядро тотально, а не «работает на валидных данных».
    for magnitude in (0.0, -5.0, 1e9, float("nan")):
        speech = _speech(magnitude=magnitude)
        assert speech.rstrip().endswith("?")
        assert ".." not in speech
        assert re.search(r"[A-Za-z]", speech) is None


# --- Вердикт (рычаг + величина) ВЫБИРАЕТ формулировку --------------------------


def test_each_lever_gets_its_own_words() -> None:
    # Пять рычагов — пять разных наблюдений: иначе «что именно я заметил» пустой звук.
    speeches = {_speech(lever=lever) for lever in Lever}
    assert len(speeches) == len(Lever)


def test_each_lever_is_matched_to_the_words_that_belong_to_it() -> None:
    # 🔴 Таблица истинности, а не «пять разных строк»: различимость мутанта не ловит —
    # перепутанная ветка (`is` → `is not` на последнем рычаге) даёт по-прежнему пять
    # разных реплик, просто не тех. Здесь пинуется САМО соответствие рычаг → слова.
    assert "тон" in _speech(lever=Lever.TONE)
    assert "длиннее" in _speech(lever=Lever.LENGTH)
    assert "осмелеть" in _speech(lever=Lever.PROACTIVITY)
    assert "мимо ушей" in _speech(lever=Lever.ADDRESSIVITY_BIAS)
    assert "шутк" in _speech(lever=Lever.HUMOR)
    # Незнакомый рычаг получает общий случай, а не чужие слова.
    assert "кое-что" in _speech(lever=cast("Lever", "рычага такого нет"))


def test_every_lever_the_detector_may_pick_has_its_own_wording() -> None:
    # Дрейф-гард: рычаги allowlist'а и формулировки — один список. Появится новый
    # рычаг без своих слов — реплика молча свалится в общий случай.
    fallback = _speech(lever=cast("Lever", "рычага такого нет"))
    for lever in Lever:
        assert _speech(lever=lever) != fallback


def test_an_unknown_lever_still_asks_instead_of_breaking() -> None:
    speech = _speech(lever=cast("Lever", "что-то новое"))

    assert speech.rstrip().endswith("?")
    assert "хочу" in speech.casefold()


def test_the_magnitude_picks_how_big_the_change_sounds() -> None:
    slight = _speech(magnitude=0.05)
    noticeable = _speech(magnitude=0.25)
    strong = _speech(magnitude=0.8)

    assert len({slight, noticeable, strong}) == 3
    assert "чуть" in slight
    assert "заметно" in noticeable
    assert "сильно" in strong


def test_the_degree_bands_sit_where_they_are_declared() -> None:
    # Границы полос — содержательный юнит на ЗНАЧЕНИЕ (MUTATION.md: модульные
    # константы mutmut не мутирует). Полосы включительны снизу и выбраны внутри реально
    # достижимого диапазона: живой потолок 0.3, поэтому «чуть» и «заметно» обязаны
    # различаться уже на нём.
    assert _speech(magnitude=0.1499) != _speech(magnitude=0.15)
    assert _speech(magnitude=0.15) == _speech(magnitude=0.4999)
    assert _speech(magnitude=0.4999) != _speech(magnitude=0.5)
    assert _speech(magnitude=0.5) == _speech(magnitude=1.0)


def test_the_speech_is_deterministic() -> None:
    assert _speech() == _speech()
    assert _message() == _message()


# --- Идентификатор правила — служебная сноска, а не часть фразы ----------------


def test_the_rule_id_is_not_part_of_bobs_words() -> None:
    assert _RULE_ID not in _speech()
    assert "/rule" not in _speech()


def test_the_message_is_bobs_words_plus_a_service_footnote() -> None:
    message = _message()
    speech, _, footnote = message.partition("\n\n")

    # Речь — первая часть и ровно та же, что Боб произнёс бы без всякой механики.
    assert speech == _speech()
    # Механика — отдельной строкой, голая команда, без слов Боба вокруг неё.
    assert footnote == f"`/rule approve {_RULE_ID}`"
    assert "\n" not in speech


def test_a_missing_rule_id_leaves_no_dangling_command() -> None:
    # Странный вход: без идентификатора команда неисполнима, поэтому сноски просто нет
    # — и на её месте не остаётся ни пустой строки, ни огрызка «/rule approve».
    message = _message(rule_id="   ")

    assert message == _speech()
    assert "/rule" not in message


def test_the_rule_id_is_trimmed_into_the_command() -> None:
    assert _message(rule_id=f"  {_RULE_ID}  ").endswith(f"`/rule approve {_RULE_ID}`")
