# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Чистые предикаты интейк-режима интерактивного терминала (BOB-083 .4).

Owner в личке ВХОДИТ в живой двусторонний claude-сеанс явной командой и ВЫХОДИТ из него
явной командой; между ними обычный текст форвардится claude в stdin (steer). Эти два
предиката — чистые детерминированные распознаватели этих команд (без LLM и I/O),
mutation-цели:

* :func:`parse_interactive_entry` — если сообщение НАЧИНАЕТСЯ командой входа
  (``/code -i <task>`` или ``/interactive <task>``) и несёт непустую задачу, возвращает
  задачу; иначе ``None``. Команда/флаг регистронезависимы, задача — дословно (обрезаны
  только внешние пробелы).
* :func:`is_interactive_exit` — ``True``, ТОЛЬКО если ВСЁ сообщение (после нормализации)
  есть команда выхода (``stop`` / ``стоп`` / ``exit`` / ``выход`` / ``/exit`` / ``/stop``
  / ``/code stop``). 🔴 Предикат НАРОЧНО узкий (точное совпадение всего сообщения, не
  «содержит стоп-токен»): в steer-режиме реплика-инструкция, лишь упоминающая стоп-слово
  («подожди, сделай иначе», «stop the server»), должна уйти claude, а не быть перехвачена
  как выход. Выход — это отдельная короткая команда, а не любое сообщение со «стоп».
"""

from __future__ import annotations

__all__ = ["is_interactive_exit", "parse_interactive_entry"]

# The two DM entry commands. ``/code -i`` reuses the familiar coder verb with an
# ``-i`` (interactive) flag; ``/interactive`` is the explicit long form.
_CODE_COMMAND = "/code"
_INTERACTIVE_FLAG = "-i"
_INTERACTIVE_COMMAND = "/interactive"

# The whole-message exit commands (case-folded, whitespace-collapsed). A DELIBERATE exact
# match — never a substring — so a steer reply mentioning a stop-word is not hijacked.
_EXIT_COMMANDS: frozenset[str] = frozenset(
    {"stop", "стоп", "exit", "выход", "/exit", "/stop", "/code stop"}
)


def _normalize(text: str) -> str:
    """Collapse surrounding/internal whitespace and case-fold for exact matching."""
    return " ".join(text.split()).casefold()


def parse_interactive_entry(text: str) -> str | None:
    """Задача входа, если ``text`` НАЧИНАЕТСЯ командой открытия интерактива; иначе ``None``.

    Распознаёт ``/code -i <task>`` и ``/interactive <task>`` (команда и флаг
    регистронезависимы). Задача возвращается дословно с обрезанными внешними пробелами;
    пустая задача (``/code -i`` без текста) → ``None`` (вход требует задачи). Команда
    должна ВЕСТИ сообщение — «just /code -i …» не вход.
    """
    stripped = text.strip()
    head, _, rest = stripped.partition(" ")
    command = head.casefold()
    if command == _INTERACTIVE_COMMAND:
        return _clean_task(rest)
    if command == _CODE_COMMAND:
        flag, _, task = rest.strip().partition(" ")
        if flag.casefold() == _INTERACTIVE_FLAG:
            return _clean_task(task)
    return None


def _clean_task(raw: str) -> str | None:
    """Trim the task; a blank task is not a valid entry (returns ``None``)."""
    task = raw.strip()
    return task or None


def is_interactive_exit(text: str) -> bool:
    """Есть ли ``text`` явная команда выхода из интерактива (всё сообщение — команда).

    ``True`` только если нормализованное сообщение ЦЕЛИКОМ равно одной из команд выхода
    (``stop`` / ``стоп`` / ``exit`` / ``выход`` / ``/exit`` / ``/stop`` / ``/code stop``).
    Узость намеренна: steer-реплика, лишь содержащая стоп-слово, — не выход (её форвардим
    claude), поэтому проверяется РАВЕНСТВО, а не вхождение токена.
    """
    return _normalize(text) in _EXIT_COMMANDS
