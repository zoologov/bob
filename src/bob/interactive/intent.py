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

BOB-087.D3 добавляет ТРОЙКУ возобновления — тот же класс чистых распознавателей:

* :func:`parse_interactive_resume` — команда возобновления долгоживущего workspace
  (``/code -r <workspace>`` / ``/resume <workspace>``).
* :func:`is_confirmation` / :func:`is_rejection` — ответ owner'а на вопрос-подтверждение
  («да» / «нет»), ТОЧНЫМ совпадением всего сообщения.

BOB-087.D5b добавляет ЧЕТВЁРТЫЙ глагол — :func:`parse_interactive_workspace`
(``/code -w <workspace> [task]`` / ``/workspace <name> [task]``): команда ОТКРЫТИЯ сессии
в долгоживущем workspace. Без неё такое дерево было нечем завести, и возобновлять было
нечего. Все четыре глагола попарно НЕ пересекаются: ни одно сообщение не читается сразу
двумя.
"""

from __future__ import annotations

__all__ = [
    "is_confirmation",
    "is_interactive_exit",
    "is_rejection",
    "parse_interactive_entry",
    "parse_interactive_resume",
    "parse_interactive_workspace",
]

# The two DM entry commands. ``/code -i`` reuses the familiar coder verb with an
# ``-i`` (interactive) flag; ``/interactive`` is the explicit long form.
_CODE_COMMAND = "/code"
_INTERACTIVE_FLAG = "-i"
_INTERACTIVE_COMMAND = "/interactive"

# The two DM resume commands (BOB-087.D3), mirroring the entry pair: ``/code -r
# <workspace>`` and the long form ``/resume <workspace>``.
_RESUME_FLAG = "-r"
_RESUME_COMMAND = "/resume"

# The DM command that OPENS a session inside a long-lived workspace (BOB-087.D5b):
# ``/code -w <workspace> [task]`` and the long form ``/workspace <name> [task]``.
_WORKSPACE_FLAG = "-w"
_WORKSPACE_COMMAND = "/workspace"

# The whole-message exit commands (case-folded, whitespace-collapsed). A DELIBERATE exact
# match — never a substring — so a steer reply mentioning a stop-word is not hijacked.
_EXIT_COMMANDS: frozenset[str] = frozenset(
    {"stop", "стоп", "exit", "выход", "/exit", "/stop", "/code stop"}
)

# The whole-message answers to Bob's resume confirmation question (BOB-087.D3). Both sets
# are exact-match only (like the exit commands) and DISJOINT, so «да, но сначала…» is not
# a yes and «нет, давай позже» is not a no — an ambiguous reply just drops the pending
# question instead of raising a session.
_CONFIRMATIONS: frozenset[str] = frozenset(
    {"да", "ага", "yes", "y", "ок", "окей", "ok", "давай", "/confirm"}
)
_REJECTIONS: frozenset[str] = frozenset({"нет", "no", "n", "отмена", "cancel", "/cancel"})


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
    return _parse_leading_command(
        text, long_command=_INTERACTIVE_COMMAND, code_flag=_INTERACTIVE_FLAG
    )


def parse_interactive_resume(text: str) -> str | None:
    """Имя workspace, если ``text`` НАЧИНАЕТСЯ командой возобновления; иначе ``None``.

    Распознаёт ``/code -r <workspace>`` и ``/resume <workspace>`` (команда и флаг
    регистронезависимы). Имя возвращается дословно с обрезанными внешними пробелами;
    пустое имя (``/resume`` без текста) → ``None``. Команда должна ВЕСТИ сообщение.

    🔴 РЕШЕНИЕ (урок BOB-076): распознаётся ТОЛЬКО явная слэш-команда. Свободный
    естественный язык («продолжи нашу сессию», «подними эпик») здесь НЕ распознаётся и
    никогда не будет: однажды дешёвая Tier-0 мис-классификация обычной болтовни запустила
    runaway-кодер. Возобновление живого claude в накопленном workspace — действие того же
    класса мощности, поэтому его инициирует только явная команда owner'а, а следом ещё и
    явное подтверждение (:func:`is_confirmation`).
    """
    return _parse_leading_command(
        text, long_command=_RESUME_COMMAND, code_flag=_RESUME_FLAG
    )


def parse_interactive_workspace(text: str) -> tuple[str, str] | None:
    """``(workspace, task)`` команды ОТКРЫТИЯ сессии в долгоживущем workspace, иначе ``None``.

    Распознаёт ``/code -w <workspace> [task]`` и ``/workspace <name> [task]`` (команда и
    флаг регистронезависимы). 🔴 BOB-087.D5b (M3): без этой команды долгоживущий workspace
    было НЕЧЕМ завести — ``open`` всегда создаёт эфемерное посессионное дерево, которое на
    ``stop`` удаляется, поэтому ``/resume`` не находил кандидата НИКОГДА, и фича замыкалась
    сама на себя.

    Имя workspace — ПЕРВЫЙ токен (ключ вроде ``BOB-087``): так у него нет двусмысленности с
    необязательной задачей, идущей следом. Задача опущена → ею становится само имя
    workspace (сессии всё равно нужна формулировка, и «BOB-087» — честная). Пустое имя
    (``/workspace`` без аргумента) → ``None``; команда обязана ВЕСТИ сообщение.

    Тот же предохранитель, что у :func:`parse_interactive_resume`: распознаётся ТОЛЬКО
    явная слэш-команда — живой claude в накапливающем работу дереве не поднимается по
    свободному тексту (урок BOB-076).
    """
    argument = _parse_leading_command(
        text, long_command=_WORKSPACE_COMMAND, code_flag=_WORKSPACE_FLAG
    )
    if argument is None:
        return None
    name, _, task = argument.partition(" ")
    return name, task.strip() or name


def _parse_leading_command(
    text: str, *, long_command: str, code_flag: str
) -> str | None:
    """Аргумент ВЕДУЩЕЙ команды ``<long_command> <arg>`` / ``/code <flag> <arg>``.

    Общая форма обеих DM-команд интерактива (вход и возобновление): команда и флаг
    сравниваются регистронезависимо, аргумент отдаётся дословно (обрезаны внешние
    пробелы), пустой аргумент и не-ведущая команда дают ``None``.
    """
    stripped = text.strip()
    head, _, rest = stripped.partition(" ")
    command = head.casefold()
    if command == long_command:
        return _clean_argument(rest)
    if command == _CODE_COMMAND:
        flag, _, argument = rest.strip().partition(" ")
        if flag.casefold() == code_flag:
            return _clean_argument(argument)
    return None


def _clean_argument(raw: str) -> str | None:
    """Trim the argument; a blank argument is not a valid command (returns ``None``)."""
    argument = raw.strip()
    return argument or None


def is_interactive_exit(text: str) -> bool:
    """Есть ли ``text`` явная команда выхода из интерактива (всё сообщение — команда).

    ``True`` только если нормализованное сообщение ЦЕЛИКОМ равно одной из команд выхода
    (``stop`` / ``стоп`` / ``exit`` / ``выход`` / ``/exit`` / ``/stop`` / ``/code stop``).
    Узость намеренна: steer-реплика, лишь содержащая стоп-слово, — не выход (её форвардим
    claude), поэтому проверяется РАВЕНСТВО, а не вхождение токена.
    """
    return _normalize(text) in _EXIT_COMMANDS


def is_confirmation(text: str) -> bool:
    """Есть ли ``text`` явное подтверждение («да») — всё сообщение целиком (BOB-087.D3).

    ``True`` только если нормализованное сообщение ЦЕЛИКОМ равно одному из согласий
    (``да`` / ``ага`` / ``yes`` / ``y`` / ``ок`` / ``окей`` / ``ok`` / ``давай`` /
    ``/confirm``). 🔴 Узость намеренна и является ПРЕДОХРАНИТЕЛЕМ: подтверждение поднимает
    живой claude в накопленном workspace, поэтому «да, но сначала покажи дифф» — НЕ «да».
    Любой другой ответ просто снимает висящий вопрос (см.
    :meth:`~bob.coding.usecases.interactive_session.InteractiveSessionManager.
    resolve_pending_resume`), а не запускает сессию.
    """
    return _normalize(text) in _CONFIRMATIONS


def is_rejection(text: str) -> bool:
    """Есть ли ``text`` явный отказ («нет») — всё сообщение целиком (BOB-087.D3).

    ``True`` только при точном совпадении всего нормализованного сообщения с одним из
    отказов (``нет`` / ``no`` / ``n`` / ``отмена`` / ``cancel`` / ``/cancel``). Множества
    согласий и отказов НЕ пересекаются, поэтому ветки «поднимаю» и «отменяю» никогда не
    спорят за один и тот же ответ.
    """
    return _normalize(text) in _REJECTIONS
