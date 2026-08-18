# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""next_backoff — чистое ядро паузы между СБОЙНЫМИ опросами (BOB-103).

Функция детерминированная и без I/O: по числу ПОДРЯД идущих сбоев отдаёт паузу
в секундах — экспонента с потолком. Ровно та развилка, которую мутация умеет
мерить (шаг экспоненты, потолок, поведение на нуле). Через границу мы проверяем
ТОЛЬКО возвращаемое число секунд.

🔴 Лечение не хуже болезни: ``consecutive_failures == 0`` (только что был успех,
или его ещё не было) обязано давать 0.0 — первый успешный опрос после возврата
сети НЕ должен ждать паузы. Это ядро того теста.
"""

from __future__ import annotations

import pytest

from bob.kernel.poll_backoff import (
    _POLL_BACKOFF_BASE_SECONDS,
    _POLL_BACKOFF_MAX_SECONDS,
    next_backoff,
)


def test_no_failures_means_no_pause() -> None:
    """0 подряд идущих сбоев → 0.0 с: успех/старт не тормозит доставку."""
    assert next_backoff(0) == 0.0


def test_first_failure_is_the_base_delay() -> None:
    """Первый сбой → базовая пауза (2**0 * base)."""
    assert next_backoff(1) == _POLL_BACKOFF_BASE_SECONDS


def test_backoff_grows_exponentially() -> None:
    """Пауза удваивается с каждым подряд идущим сбоем (пока не упрётся в потолок)."""
    assert next_backoff(2) == _POLL_BACKOFF_BASE_SECONDS * 2
    assert next_backoff(3) == _POLL_BACKOFF_BASE_SECONDS * 4
    assert next_backoff(4) == _POLL_BACKOFF_BASE_SECONDS * 8


def test_backoff_is_capped() -> None:
    """Растёт монотонно, но не выше скромного потолка (быстрое восстановление)."""
    assert next_backoff(100) == _POLL_BACKOFF_MAX_SECONDS


def test_cap_is_modest() -> None:
    """Потолок скромный (≤30 с) — после возврата сети доставка не ждёт вечно."""
    assert _POLL_BACKOFF_MAX_SECONDS <= 30.0


def test_backoff_never_decreases() -> None:
    """Монотонно неубывающая по числу сбоев — ни одна ступень не проседает."""
    delays = [next_backoff(n) for n in range(0, 20)]
    assert delays == sorted(delays)


def test_negative_failures_rejected() -> None:
    """Отрицательное число сбоев — программная ошибка, не молча 0."""
    with pytest.raises(ValueError, match="consecutive_failures"):
        next_backoff(-1)
