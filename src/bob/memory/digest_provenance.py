# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Формат провенанса дайджеста — «из какого окна я это помню» (bob-g7t).

Свёртка (:mod:`bob.memory.usecases.consolidate_memory`) записывает рядом с дайджестом
ts-диапазон его источников: ``<самый ранний>..<самый поздний>``. До bob-g7t этот формат
был односторонним — его только писали. Починка приватности старых дайджестов читает его
обратно (по окну находятся источники, по источникам — метка видимости), поэтому писатель
и читатель обязаны знать ОДНО определение формата; оно живёт здесь.

Значения уже лежат в живой базе (21 дайджест) — формат исторический, не выбранный
заново. Чисто и без I/O.
"""

from __future__ import annotations

__all__ = ["parse_provenance_window", "provenance_window"]

# Разделитель концов окна. ISO-8601 несёт одиночную точку (микросекунды), но никогда
# двойную, поэтому «..» однозначно делит диапазон.
_SEPARATOR = ".."
_WINDOW_ENDS = 2


def provenance_window(first_ts: str, last_ts: str) -> str:
    """Собрать провенанс дайджеста из ts самого раннего и самого позднего источника."""
    return f"{first_ts}{_SEPARATOR}{last_ts}"


def parse_provenance_window(value: str | None) -> tuple[str, str] | None:
    """Разобрать провенанс обратно в ``(первый ts, последний ts)`` — или ``None``.

    ``None`` означает «окно не восстановилось»: значения нет, оно пустое, в нём не ровно
    два конца или один из концов пуст. Половинчатый разбор здесь недопустим — по окну
    ищутся источники, а по источникам решается ПРИВАТНОСТЬ дайджеста, так что
    придуманное окно дало бы неверный вердикт с полной уверенностью. Пусть лучше
    вызывающий получит честное «не знаю» и ответит консервативно.
    """
    if value is None:
        return None
    ends = value.strip().split(_SEPARATOR)
    if len(ends) != _WINDOW_ENDS or not all(end.strip() for end in ends):
        return None
    return (ends[0].strip(), ends[1].strip())
