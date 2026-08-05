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
* :func:`ground_mentions` — вычистить СВОЙ исходящий текст: подтверждённый тег остаётся,
  неподтверждённый теряет «собаку» и остаётся именем.
* :func:`demote_mentions` — снять «собаку» со ВСЕХ тегов БЕЗУСЛОВНО: чужой текст, который
  Боб лишь цитирует, никого не дёргает.

🔴 Правило, ради которого модуль и существует: **выдуманный тег хуже отсутствующего.**
Тег, которого нет в ростере, — это утверждение о человеке, которого Боб не может
проверить: он либо промахнётся мимо адресата, либо ткнёт в постороннего. Поэтому ника нет
→ обращаемся по имени, а «собака» из текста снимается. Из имени тег не собирается никогда.

🔴 Второе правило (BOB-090.B-fix2): **подменённый тег хуже выдуманного.** Имя в ростере —
это Telegram full_name, свободный текст, который человек ставит себе САМ, поэтому «совпало
по имени» не равно «это тот самый человек». Отсюда две поправки: имя, под которое подходит
БОЛЬШЕ ОДНОГО человека, тега не получает вовсе (неоднозначность разрешается в пользу
обычного слова, а не догадки), а owner опознаётся структурно — по ``sender_id`` из
конфига, — и потому среди тёзок обращение достаётся ему, а не самозванцу.

🔴 Третье правило: заземлять до настоящего ника можно ТОЛЬКО то, что пишет сам Боб. Текст,
который он цитирует за другим человеком, проходит :func:`demote_mentions` — иначе цитата
«@Norman, отдай ключи» превращалась бы в настоящий пинг ``@NormanGri`` от имени Боба.

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

__all__ = [
    "PersonHandle",
    "demote_mentions",
    "ground_mentions",
    "handles_from",
    "mention_for",
]

# Упоминание: «собака» + слово. ``\w`` покрывает и кириллицу (Python 3, str) — именно
# кириллический «@Норман» и был дефектом. Отрицательный lookbehind отсекает почту
# (``bob@example.com``) и «100@шт»: там «собака» приклеена к слову слева.
_MENTION = re.compile(r"(?<![\w@])@(\w+)")


@dataclass(frozen=True, slots=True)
class PersonHandle:
    """Человек как адресуемое лицо: имя, ник (если он вообще есть) и «это owner».

    ``username`` — БЕЗ «собаки» (как отдаёт Telegram) и ``None``, когда ника нет: в
    Telegram он необязателен, и это нормальное состояние, а не отсутствие данных.

    ``is_owner`` (BOB-090.B-fix2) — опознание ЛИЧНОСТИ, а не строки: ставится по
    ``sender_id``, который человек о себе не заявляет. Нужно ровно для одного — чтобы
    среди тёзок обращение к owner'у не уехало на постороннего, назвавшегося его именем.
    """

    name: str
    username: str | None
    is_owner: bool = False


def handles_from(
    impressions: Sequence[FirstImpression], *, owner_id: int | None = None
) -> tuple[PersonHandle, ...]:
    """Собрать адресуемые лица из ростера (чисто).

    Имя разрешается тем же фолбэком, что и у ростера (:func:`~bob.social.roster.member_name`
    — ``display_name`` или голова заметки «{имя} — …»), поэтому легаси-строка без имени всё
    равно называется. Безымянная строка отбрасывается: обратиться «никак» нельзя, а
    придумывать имя — тот же дефект, что и придумывать тег.

    ``owner_id`` помечает в ростере owner'а по ЕГО ID (из конфига). Не передан — никто не
    помечен, и разрешение имён работает строго по однозначности: это консервативная
    сторона (тег скорее не поставится, чем поставится не тому).
    """
    handles = (
        PersonHandle(
            name=member_name(impression).strip(),
            username=impression.username,
            is_owner=owner_id is not None and impression.sender_id == owner_id,
        )
        for impression in impressions
    )
    return tuple(handle for handle in handles if handle.name)


def mention_for(name: str, people: Sequence[PersonHandle]) -> str:
    """Как обратиться к ``name``: реальный ``@ник`` или само имя (чисто).

    Ник берётся ТОЛЬКО из ростера и только для человека, чьё имя совпало ОДНОЗНАЧНО (без
    учёта регистра; полное имя «Паша Иванов» узнаётся и по первому слову — в просьбе людей
    зовут коротко). Ника нет, человек незнаком, имя пустое, имя носят двое — возвращается
    то, что передали: 🔴 из имени тег не собирается никогда, а из спорного имени — тем более.
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


def demote_mentions(text: str) -> str:
    """Снять «собаку» со ВСЕХ упоминаний в ЧУЖОМ тексте (чисто, BOB-090.B-fix2).

    Понижение без единого исключения: тег остаётся обычным словом, кем бы он ни был —
    выдумкой, совпадением с ником из ростера или настоящим ником. Применяется к тексту,
    который Боб лишь ЦИТИРУЕТ (слова просителя, чужое имя), потому что заземление
    (:func:`ground_mentions`) не только снимает «собаку», но и ПОВЫШАЕТ имя до реального
    ника: цитата «@Norman, отдай ключи» уезжала в комнату настоящим пингом ``@NormanGri``
    от имени Боба — человека дёргал текст, который Боб не писал.

    Ростер здесь не нужен и не спрашивается: понижение не может ошибиться в чью-либо
    пользу. Текст без упоминаний возвращается тем же объектом; идемпотентно.
    """
    if not _MENTION.search(text):
        return text
    return _MENTION.sub(lambda match: match.group(1), text)


def _find(name: str, people: Sequence[PersonHandle]) -> PersonHandle | None:
    """Найти человека по имени ОДНОЗНАЧНО, иначе — никого (чисто).

    Совпадением считается имя целиком или его первое слово («Паша» ↔ «Паша Иванов»): в
    просьбе людей зовут коротко, и обе формы равноправны — тем более что «точное»
    совпадение как раз и подделывается легче всего (посторонний ставит себе full_name
    «Вова», а owner записан «Вова Зоологов»).

    🔴 Спорное имя тега не получает. Единственное исключение — owner: он опознан по
    ``sender_id``, то есть структурно, а не по строке, которую любой может себе взять,
    поэтому среди тёзок обращение достаётся ему. Ни того ни другого нет — ``None``, и
    вызывающий оставит обычное слово (подменённый тег хуже отсутствующего).
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None
    matches = [handle for handle in people if _name_matches(handle, wanted)]
    if len(matches) == 1:
        return matches[0]
    owners = [handle for handle in matches if handle.is_owner]
    if len(owners) == 1:
        return owners[0]
    return None


def _name_matches(handle: PersonHandle, wanted: str) -> bool:
    """Совпадает ли имя человека с искомым — целиком или своим первым словом (чисто)."""
    name = handle.name.casefold()
    return name == wanted or name.split()[0] == wanted
