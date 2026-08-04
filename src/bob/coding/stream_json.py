# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""stream_json — транспортный примитив потока ``claude --output-format stream-json``.

ОДНА ответственность: как читается ОДНА строка NDJSON-потока claude — её разбор
(:func:`parse_event`) и предел буфера, за которым чтение строки ломается
(:data:`STREAM_LIMIT`). Ни спавна, ни процесса, ни политики: чистая функция + константа,
рядом с чистым рендером тех же событий (:mod:`bob.coding.stream_render`).

🔴 BOB-087.E (bob-6u2): оба примитива жили ПРИВАТНЫМИ внутри одного адаптера
(``claude_runner``), и второй транспорт — раннер живого терминала — тянул их оттуда
через ``_``-имена. Когда живой терминал уехал в собственный bounded context
(:mod:`bob.interactive`), это стало ещё и запрещённым ребром «чужой модуль → adapters».
Общее у обоих транспортов ровно одно: формат потока, — и он теперь живёт здесь, на
общей доменной поверхности, а оба адаптера читают его отсюда. Дублировать 16 МиБ и
разбор строки в двух местах было нельзя: расхождение вернуло бы краш BOB-084.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

__all__ = ["STREAM_LIMIT", "parse_event"]

# StreamReader buffer limit for a spawned ``claude`` process. asyncio's default is
# 64 KiB, but ``claude --output-format stream-json`` routinely emits single lines far
# larger (big tool results, file reads, long assistant messages); ``readline()`` on a
# line past the limit raises ``LimitOverrunError`` — surfaced as ``ValueError`` — and
# crashes the read loop (the BOB-084 production crash). 16 MiB is generous headroom
# (real lines are well under 1 MiB).
STREAM_LIMIT = 16 * 1024 * 1024


def parse_event(line: str) -> Mapping[str, object] | None:
    """Parse one NDJSON line into an event mapping; tolerate blank/garbage lines."""
    text = line.strip()
    if not text:
        return None
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, Mapping):
        return decoded
    return None
