# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Голос Боба, когда он уходит на обновление и когда возвращается (BOB-094 срез 1).

Канон BOB-090.D: рестарт — это ГОЛОС Боба (его бот по-человечески предупреждает,
что обновляется, и говорит, что вернулся), а НЕ строка деплой-скрипта. Образец —
:mod:`bob.proactivity.rule_voice` (BOB-096): живые, не-скриптованные варианты,
детерминированный выбор БЕЗ ``random``/времени (в этом окружении они запрещены).

Тесты пинают:

* каждый ``RestartMoment`` даёт НЕПУСТУЮ, человеческую реплику;
* реплики «ухожу» и «вернулся» РАЗНЫЕ по смыслу (уход ≠ возвращение);
* есть НЕСКОЛЬКО вариантов формулировок (не один зашитый шаблон) — иначе это
  ровно та скриптованность, против которой написан модуль;
* выбор ДЕТЕРМИНИРОВАН по маркеру (один и тот же маркер → одна и та же реплика);
* ядро ТОТАЛЬНО — любой маркер (пустой, странный) даёт валидную реплику.
"""

from __future__ import annotations

import hashlib
import inspect

from bob.proactivity import restart_voice as restart_voice_module
from bob.proactivity.restart_voice import (
    _LEAVING,
    _RETURNED,
    RestartMoment,
    restart_voice,
)


def _variants(moment: RestartMoment) -> set[str]:
    """Собрать все реплики момента по широкому вееру маркеров."""
    return {restart_voice(moment, marker=f"marker-{n}") for n in range(64)}


def test_leaving_speaks_a_nonempty_human_line() -> None:
    line = restart_voice(RestartMoment.LEAVING, marker="boot-1")
    assert line.strip(), "уход на обновление обязан звучать репликой, не пустой строкой"


def test_returned_speaks_a_nonempty_human_line() -> None:
    line = restart_voice(RestartMoment.RETURNED, marker="boot-1")
    assert line.strip(), "возвращение обязано звучать репликой, не пустой строкой"


def test_leaving_and_returned_are_different_in_meaning() -> None:
    # Один и тот же маркер, но два РАЗНЫХ момента — реплики не должны совпасть:
    # «ухожу обновиться» и «вернулся, обновился» — противоположные события.
    marker = "same-marker"
    leaving = restart_voice(RestartMoment.LEAVING, marker=marker)
    returned = restart_voice(RestartMoment.RETURNED, marker=marker)
    assert leaving != returned


def test_leaving_has_several_live_variants() -> None:
    # Несколько формулировок, а не один зашитый шаблон (анти-скриптованность).
    assert len(_variants(RestartMoment.LEAVING)) >= 3


def test_returned_has_several_live_variants() -> None:
    assert len(_variants(RestartMoment.RETURNED)) >= 3


def test_leaving_picks_from_the_leaving_fan_and_never_the_return_fan() -> None:
    # 🔴 Пинует ветку выбора веера (moment): уход обязан прийти ИЗ реплик ухода, а не
    # возвращения. Иначе перепутанное условие «is not RETURNED» осталось бы незамеченным.
    for n in range(64):
        line = restart_voice(RestartMoment.LEAVING, marker=f"m{n}")
        assert line in _LEAVING
        assert line not in _RETURNED


def test_returned_picks_from_the_return_fan_and_never_the_leaving_fan() -> None:
    for n in range(64):
        line = restart_voice(RestartMoment.RETURNED, marker=f"m{n}")
        assert line in _RETURNED
        assert line not in _LEAVING


def test_marker_to_variant_is_a_pinned_golden_mapping() -> None:
    # 🔴 Пинует, КАКОЙ именно байт хеша и оператор выбирают вариант: подмена ``digest[0]``
    # на ``digest[1]`` или ``%`` на ``/`` сдвинет отображение маркер→реплика, и золотые
    # пары ниже перестанут сходиться. Значения зафиксированы прогоном исправного ядра.
    assert restart_voice(RestartMoment.LEAVING, marker="boot-1") == _LEAVING[
        _sha_first_byte("boot-1") % len(_LEAVING)
    ]
    assert restart_voice(RestartMoment.RETURNED, marker="boot-1") == _RETURNED[
        _sha_first_byte("boot-1") % len(_RETURNED)
    ]


def _sha_first_byte(marker: str) -> int:
    return hashlib.sha256(marker.encode("utf-8")).digest()[0]


def test_choice_is_deterministic_for_a_marker() -> None:
    # Одинаковый вход → одинаковый результат (никакого random/времени).
    first = restart_voice(RestartMoment.LEAVING, marker="stable")
    second = restart_voice(RestartMoment.LEAVING, marker="stable")
    assert first == second


def test_marker_varies_the_chosen_variant() -> None:
    # Выбор ДЕЙСТВИТЕЛЬНО зависит от маркера — разные маркеры дают ≥2 разных реплик.
    seen = {restart_voice(RestartMoment.LEAVING, marker=f"m{n}") for n in range(32)}
    assert len(seen) >= 2


def test_core_is_total_on_any_marker() -> None:
    # Пустой / странный маркер — всё равно валидная непустая реплика (тотальность).
    for marker in ("", " ", "\n", "\t", "любой-мусор"):
        for moment in (RestartMoment.LEAVING, RestartMoment.RETURNED):
            assert restart_voice(moment, marker=marker).strip()


def test_core_is_pure_no_io_imports() -> None:
    # Ядро без I/O и без источников недетерминизма: ни random, ни time в исходнике.
    src = inspect.getsource(restart_voice_module)
    assert "import random" not in src
    assert "import time" not in src
    assert "datetime" not in src
