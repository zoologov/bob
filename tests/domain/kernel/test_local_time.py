# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Время для человека: пояс процесса и явное смещение (BOB-116 D11, bob-i83.15).

Решение координатора: сообщения владельцу, GUPPI ``/status`` и эпизод «я молчал» говорят о
времени в ОДНОМ поясе — поясе процесса — и называют его смещение (``+03:00``), без «UTC».
Пояс здесь всегда задан явно фиксированным смещением: тест, полагающийся на пояс машины,
был бы вакуумным на машине с тем же поясом.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from bob.kernel.local_time import in_local_zone, utc_offset_label

_MOMENT_UTC = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        (UTC, "+00:00"),
        (timezone(timedelta(hours=3)), "+03:00"),
        (timezone(timedelta(hours=5, minutes=45)), "+05:45"),
        (timezone(-timedelta(hours=9, minutes=30)), "-09:30"),
    ],
)
def test_offset_label_names_the_offset_with_sign_hours_and_minutes(
    tz: tzinfo, expected: str
) -> None:
    assert utc_offset_label(_MOMENT_UTC.astimezone(tz)) == expected


def test_offset_label_of_a_naive_moment_is_empty() -> None:
    naive = datetime(2026, 10, 1, 6, 10)  # noqa: DTZ001 - наивное время — сам предмет теста
    assert utc_offset_label(naive) == ""


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        (timezone(timedelta(hours=3)), datetime(2026, 10, 1, 9, 10)),  # noqa: DTZ001
        (timezone(-timedelta(hours=9, minutes=30)), datetime(2026, 9, 30, 20, 40)),  # noqa: DTZ001
    ],
)
def test_aware_moment_is_moved_into_the_requested_zone(tz: tzinfo, expected: datetime) -> None:
    moved = in_local_zone(_MOMENT_UTC, tz)
    assert moved.replace(tzinfo=None) == expected
    assert moved.utcoffset() == tz.utcoffset(None)
    assert moved == _MOMENT_UTC  # тот же момент, другой пояс


def test_default_zone_is_the_process_local_one() -> None:
    assert in_local_zone(_MOMENT_UTC).utcoffset() == _MOMENT_UTC.astimezone().utcoffset()


def test_naive_moment_is_left_as_is() -> None:
    naive = datetime(2026, 10, 2, 23, 5)  # noqa: DTZ001 - пересчитывать не из чего
    assert in_local_zone(naive, timezone(timedelta(hours=3))) is naive
