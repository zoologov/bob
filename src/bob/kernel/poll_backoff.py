# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Пауза между СБОЙНЫМИ опросами Telegram — одно правило на весь опрос (BOB-103).

ОДНА ответственность: по числу ПОДРЯД идущих сбоев опроса вернуть паузу в
секундах. Ничего не спит и не смотрит в окружение — это чистый детерминированный
вердикт, отделённый от async-оркестрации в :mod:`bob.infrastructure.telegram.multibot`.

Корень бага (BOB-103): поллинг крутится ``periodic(poll, interval_seconds=0.0)``
— при живой сети это правильно (``get_updates`` держит long-poll и сам задаёт
темп), но на обрыве сети ``get_updates`` бросает МГНОВЕННО, и цикл с интервалом 0
бьёт снова сразу → хот-луп (~30 тыс. строк «poll failed» в сутки на бота). Пауза,
растущая с числом подряд идущих сбоев, гасит хот-луп.

Три свойства — и каждое обязано быть именно таким:

* **0 сбоев → 0.0 с.** Только что был успех (счётчик сброшен), или сбоя ещё не
  было. 🔴 Лечение не хуже болезни: первый УСПЕШНЫЙ опрос после возврата сети НЕ
  ждёт паузы — доставка мгновенна, а не через потолок.
* **экспонента.** Пауза удваивается с каждым подряд идущим сбоем
  (``base * 2**(n-1)``), чтобы затяжной обрыв не оставался в частоте отказа.
* **скромный потолок.** Рост упирается в :data:`_POLL_BACKOFF_MAX_SECONDS`
  (≤30 с), чтобы после возврата сети первый успешный опрос случился быстро, а не
  через минуты накопленной паузы.
"""

from __future__ import annotations

__all__ = ["next_backoff"]

# Базовая пауза на ПЕРВЫЙ сбой (секунды). Дальше удваивается на каждый следующий
# подряд идущий сбой, пока не упрётся в потолок.
_POLL_BACKOFF_BASE_SECONDS = 1.0

# Скромный потолок паузы (секунды). 🔴 Держим ≤30 с намеренно: чем ниже потолок,
# тем быстрее доставка после возврата сети — но достаточно высокий, чтобы гасить
# хот-луп на затяжном обрыве.
_POLL_BACKOFF_MAX_SECONDS = 30.0


def next_backoff(consecutive_failures: int) -> float:
    """Пауза в секундах после ``consecutive_failures`` подряд идущих сбоев опроса.

    ``0`` (успех / старт) → ``0.0``; иначе экспонента ``base * 2**(n-1)`` с
    потолком :data:`_POLL_BACKOFF_MAX_SECONDS`. Отрицательное число сбоев —
    программная ошибка (счётчик сбоев не бывает отрицательным), поэтому
    отвергается, а не молча трактуется как ноль.
    """
    if consecutive_failures < 0:
        msg = f"consecutive_failures must be non-negative, got {consecutive_failures}"
        raise ValueError(msg)
    if consecutive_failures == 0:
        return 0.0
    grown: float = _POLL_BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1))
    return min(grown, _POLL_BACKOFF_MAX_SECONDS)
