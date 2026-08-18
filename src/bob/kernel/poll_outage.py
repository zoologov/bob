# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Сигнал «я оглох» — один вердикт поверх счётчика подряд идущих сбоев (BOB-094).

ОДНА ответственность: по числу ПОДРЯД идущих сбоев опроса Telegram (счётчик
BOB-103 ``_poll_failures[identity]``) и порогу сказать «оглох / нет». Ничего не
логирует и не смотрит в окружение — чистый детерминированный вердикт, отделённый
от async-оркестрации и логирования в
:mod:`bob.infrastructure.telegram.multibot`.

Зачем отдельно от :func:`~bob.kernel.poll_backoff.next_backoff`: backoff отвечает
«сколько ждать» (гасит хот-луп), а это ядро — «пора ли объявить диагноз». Разные
ответственности, разные развилки.

🔴 Единичный блип — НЕ «оглох». Порог обязан быть > 1, иначе первый же рутинный
обрыв long-poll (``ServerDisconnectedError``) объявил бы Боба глухим и наблюдатель
захлебнулся бы ложными тревогами. Порог ≤ 1 отвергается как программная ошибка, а
не молча принимается.

🔴 Ограничение, названное честно: этот сигнал — вход для НАБЛЮДАТЕЛЯ (строка в
логе, отражение в ``./bob status``), а НЕ Telegram-алерт. Боб, который оглох, по
определению не может сам о себе написать в Telegram (его канал и есть то, что
легло) — полноценный алерт требует ВНЕШНЕГО канала и делается отдельной работой
(RFC BOB-094 «Что НЕ делаем»). Ядро сознательно не притворяется алертом.
"""

from __future__ import annotations

__all__ = ["outage_state"]

# Минимально допустимый порог «оглох». 🔴 Строго > 1: при пороге 1 единичный блип
# стал бы диагнозом. Порог ниже этого — программная ошибка конфигурации.
_MIN_OUTAGE_THRESHOLD = 2


def outage_state(consecutive_failures: int, *, threshold: int) -> bool:
    """«Оглох ли Боб» — ``consecutive_failures`` подряд идущих сбоев ≥ ``threshold``.

    ``consecutive_failures`` — счётчик BOB-103 (сброшенный первым успехом, растёт
    на каждом сетевом сбое ``get_updates``). ``threshold`` — сколько сбоев подряд
    считаем «оглох», из конфига ``telegram.outage_threshold``.

    Возвращает ``True``, когда сбоев набралось не меньше порога (граница ≥: ровно
    порог — уже оглох). ``threshold`` ниже :data:`_MIN_OUTAGE_THRESHOLD` (> 1)
    отвергается — единичный блип НЕ диагноз. Отрицательное число сбоев тоже
    программная ошибка (счётчик не бывает отрицательным).
    """
    if threshold < _MIN_OUTAGE_THRESHOLD:
        msg = (
            f"threshold must be > 1 (a single blip is not an outage), "
            f"got {threshold}"
        )
        raise ValueError(msg)
    if consecutive_failures < 0:
        msg = (
            f"consecutive_failures must be non-negative, "
            f"got {consecutive_failures}"
        )
        raise ValueError(msg)
    return consecutive_failures >= threshold
