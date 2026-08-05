# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Mention — чистое ядро «как обратиться к человеку» (BOB-090.B3).

Живой дефект (эпизод 3088): Боб написал «@Норман», хотя ник человека — ``@NormanGri``.
Корень не в модели, а в памяти: ``@username`` не хранился НИГДЕ, взять тег было неоткуда,
и модель дописала правдоподобное. Здесь живёт обратная сторона — обращение, ЗАЗЕМЛЁННОЕ
на ростер (BOB-080):

* :class:`PersonHandle` — один человек как адресуемое лицо: имя + необязательный ник.
* :func:`handles_from` — ростер (накопленные первые впечатления) → такие лица.
* :func:`mention_for` — как обратиться к названному человеку: реальный ``@ник`` или имя.
* :func:`ground_mentions` — вычистить исходящий текст: подтверждённый тег остаётся,
  неподтверждённый теряет «собаку» и остаётся именем.

🔴 Правило, ради которого модуль и существует: **выдуманный тег хуже отсутствующего.**
Тег, которого нет в ростере, — это утверждение о человеке, которого Боб не может
проверить: он либо промахнётся мимо адресата, либо ткнёт в постороннего. Поэтому ника нет
→ обращаемся по имени, а «собака» из текста снимается. Из имени тег не собирается никогда.

Чисто и детерминированно: никакого I/O, одинаковый вход → одинаковый результат.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.social.roster import member_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.social.first_impression import FirstImpression

__all__ = ["PersonHandle", "ground_mentions", "handles_from", "mention_for"]

# Упоминание: «собака» + слово. ``\w`` покрывает и кириллицу (Python 3, str) — именно
# кириллический «@Норман» и был дефектом. Отрицательный lookbehind отсекает почту
# (``bob@example.com``) и «100@шт»: там «собака» приклеена к слову слева.
_MENTION = re.compile(r"(?<![\w@])@(\w+)")


@dataclass(frozen=True, slots=True)
class PersonHandle:
    """Человек как адресуемое лицо: имя и ник, если он вообще есть.

    ``username`` — БЕЗ «собаки» (как отдаёт Telegram) и ``None``, когда ника нет: в
    Telegram он необязателен, и это нормальное состояние, а не отсутствие данных.
    """

    name: str
    username: str | None


def handles_from(impressions: Sequence[FirstImpression]) -> tuple[PersonHandle, ...]:
    """Собрать адресуемые лица из ростера (чисто).

    Имя разрешается тем же фолбэком, что и у ростера (:func:`~bob.social.roster.member_name`
    — ``display_name`` или голова заметки «{имя} — …»), поэтому легаси-строка без имени всё
    равно называется. Безымянная строка отбрасывается: обратиться «никак» нельзя, а
    придумывать имя — тот же дефект, что и придумывать тег.
    """
    handles = (
        PersonHandle(name=member_name(impression).strip(), username=impression.username)
        for impression in impressions
    )
    return tuple(handle for handle in handles if handle.name)


def mention_for(name: str, people: Sequence[PersonHandle]) -> str:
    """Как обратиться к ``name``: реальный ``@ник`` или само имя (чисто).

    Ник берётся ТОЛЬКО из ростера и только для человека, чьё имя совпало (без учёта
    регистра; полное имя «Паша Иванов» узнаётся и по первому слову — в просьбе людей
    зовут коротко). Ника нет, человек незнаком, имя пустое — возвращается то, что
    передали: 🔴 из имени тег не собирается никогда.
    """
    match = _find(name, people)
    if match is None or match.username is None:
        return name
    return f"@{match.username}"


def ground_mentions(text: str, people: Sequence[PersonHandle]) -> str:
    """Заземлить упоминания в исходящем тексте на ростер (чисто).

    Каждое ``@слово`` проверяется по ростеру: совпало с настоящим ником — остаётся как
    есть (регистр не трогаем, Telegram его не различает); совпало с ИМЕНЕМ человека, у
    которого ник известен, — заменяется на настоящий ``@ник`` (ровно эпизод 3088); ничем
    не подтверждено — теряет «собаку» и остаётся обычным словом.

    Текст без упоминаний возвращается тем же объектом, поэтому обычная отправка
    байт-в-байт не зависит от ростера. Идемпотентно: повторный прогон ничего не меняет.
    """
    if not _MENTION.search(text):
        return text
    usernames = {
        handle.username.casefold() for handle in people if handle.username is not None
    }

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.casefold() in usernames:
            return match.group(0)
        person = _find(token, people)
        if person is not None and person.username is not None:
            return f"@{person.username}"
        return token

    return _MENTION.sub(_replace, text)


def _find(name: str, people: Sequence[PersonHandle]) -> PersonHandle | None:
    """Найти человека по имени: точное совпадение, затем по первому слову имени."""
    wanted = name.strip().casefold()
    if not wanted:
        return None
    for handle in people:
        if handle.name.casefold() == wanted:
            return handle
    for handle in people:
        if handle.name.split()[0].casefold() == wanted:
            return handle
    return None
