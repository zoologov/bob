# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Числа, похожие на идентификаторы Telegram, в тексте трекаемой конфигурации (BOB-116).

ОДНА ответственность: найти в тексте каждую серию из шести и более цифр, как бы её ни
разбили. Репозиторий публичный, и id владельца (от шести цифр) или группы (тринадцать) не
должен попасть ни в значение, ни в комментарий. Его гасят разделителем — ``-100_437_294``,
``-100 4372 9473 07``, табуляцией или неразрывным пробелом, — поэтому любые горизонтальные
разделители МЕЖДУ цифрами, сколько бы их ни было подряд, считаются частью числа.

Разделителем НЕ считаются запятая (список ``[600, 3600]`` — это четыре числа, а не одно),
дефис (дата ``2026-10-21``), точка и двоеточие (``5.9``, ``06:10``): они разделяют разные
величины, и склейка дала бы ложную находку на честном тексте.

Одно исключение — значение ``runtime.log_max_bytes`` на его строке (размер ротации лога).
Оно снимается ДО склейки: иначе id, приписанный к значению через пробел, склеился бы с ним и
ушёл вместе с исключением.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["DigitRun", "has_log_rotation_value", "id_like_digit_runs"]

# Шесть цифр — самый короткий id пользователя Telegram; у группы их тринадцать.
_ID_LIKE_DIGIT_RUN = re.compile(r"\d{6,}")
# Подчёркивание, пробел, табуляция, неразрывный, тонкий и узкий неразрывный пробелы.
_DIGIT_SEPARATOR = re.compile(r"(?<=\d)[_ \t   ]+(?=\d)")
_LOG_MAX_BYTES_VALUE = re.compile(r"^(\s*log_max_bytes:\s*)\d+", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class DigitRun:
    """Одна найденная серия: номер строки (с единицы) и цифры без разделителей."""

    line: int
    digits: str


def id_like_digit_runs(text: str) -> list[DigitRun]:
    """Каждая серия из 6+ цифр в ``text``, кроме значения ``log_max_bytes``."""
    exempted = _LOG_MAX_BYTES_VALUE.sub(r"\1", text)
    joined = _DIGIT_SEPARATOR.sub("", exempted)
    return [
        DigitRun(line=number, digits=run)
        for number, line in enumerate(joined.splitlines(), start=1)
        for run in _ID_LIKE_DIGIT_RUN.findall(line)
    ]


def has_log_rotation_value(text: str) -> bool:
    """Есть ли в тексте то значение, ради которого существует исключение."""
    return _LOG_MAX_BYTES_VALUE.search(text) is not None
