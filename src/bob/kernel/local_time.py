# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Время для человека: момент в поясе процесса и его явное смещение (BOB-116 D11).

ОДНА ответственность: решить, в каком поясе Боб называет время человеку, и как он этот пояс
подписывает. Решение одно на всех (координатор, bob-i83.15): сообщения владельцу о здоровье
LLM, GUPPI ``/status`` и эпизод «я молчал» говорят в **поясе процесса** — том, что настроен
на машине Боба, — и называют смещение явно (``06:10 +03:00``), без подписи «UTC». Часы Боба
идут в UTC; без этого модуля три места говорили в двух разных поясах, и только одно из них
это подписывало.

Здесь только два решения, а не формат строки: дату и часы каждое место раскладывает своими
словами («с 1 октября 06:10», «2026-10-01 06:10»).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

__all__ = ["in_local_zone", "utc_offset_label"]

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60


def in_local_zone(moment: datetime, tz: tzinfo | None = None) -> datetime:
    """Тот же момент в поясе ``tz``; ``None`` — пояс процесса. Наивный — как есть.

    Наивное время не пересчитывается: неизвестно, в каком поясе оно записано.
    """
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(tz)


def utc_offset_label(moment: datetime) -> str:
    """Смещение пояса момента: ``+03:00``, ``-09:30``, ``+00:00``; у наивного — пусто."""
    offset = moment.utcoffset()
    if offset is None:
        return ""
    total = int(offset.total_seconds())
    sign = "-" if total < 0 else "+"
    hours, rest = divmod(abs(total), _SECONDS_PER_HOUR)
    return f"{sign}{hours:02d}:{rest // _SECONDS_PER_MINUTE:02d}"
