# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""outage_state — чистое ядро сигнала «я оглох» (BOB-094 срез 2).

Функция детерминированная и без I/O: по числу ПОДРЯД идущих сбоев опроса
(счётчик BOB-103) и порогу отдаёт булев вердикт «оглох» — сбоев ≥ порога.
Ровно та развилка порога, которую мутация умеет мерить (граница ≥, поведение на
нуле, отказ на негодном пороге). Через границу проверяем ТОЛЬКО булев результат.

🔴 Единичный блип — НЕ «оглох»: порог обязан быть > 1, иначе первый же сетевой
чих объявил бы Боба глухим. Это ядро анти-ложной-тревоги (RFC «наблюдаемость»).
"""

from __future__ import annotations

import pytest

from bob.kernel.poll_outage import outage_state


def test_no_failures_is_not_an_outage() -> None:
    """0 подряд идущих сбоев (успех/старт) → не оглох."""
    assert outage_state(0, threshold=3) is False


def test_below_threshold_is_not_an_outage() -> None:
    """Сбоев меньше порога → ещё не оглох (транзиент, не диагноз)."""
    assert outage_state(2, threshold=3) is False


def test_exactly_threshold_is_an_outage() -> None:
    """Сбоев РОВНО порог → оглох (граница ≥, не >)."""
    assert outage_state(3, threshold=3) is True


def test_above_threshold_is_an_outage() -> None:
    """Сбоев больше порога → по-прежнему оглох."""
    assert outage_state(7, threshold=3) is True


def test_single_blip_is_never_an_outage_at_the_minimum_threshold() -> None:
    """🔴 Единичный блип ≠ оглох: при минимально допустимом пороге (2) один сбой молчит."""
    assert outage_state(1, threshold=2) is False
    assert outage_state(2, threshold=2) is True


def test_threshold_of_one_is_rejected() -> None:
    """🔴 Порог ≤ 1 сделал бы единичный блип «оглохом» — программная ошибка, отвергается."""
    with pytest.raises(ValueError, match="threshold"):
        outage_state(1, threshold=1)


def test_threshold_of_zero_is_rejected() -> None:
    """Порог 0 (или отрицательный) бессмыслен для «оглох» — отвергается."""
    with pytest.raises(ValueError, match="threshold"):
        outage_state(0, threshold=0)


def test_negative_failures_is_rejected() -> None:
    """Счётчик подряд идущих сбоев не бывает отрицательным — программная ошибка."""
    with pytest.raises(ValueError, match="consecutive_failures"):
        outage_state(-1, threshold=3)
