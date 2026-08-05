# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Destination — чистое ядро «куда именно писать» (BOB-090.B2).

До этого среза исходящего адреса не существовало как понятия: ответ всегда уходил в
``chat_id`` текущего хода, поэтому просьба из лички «расскажи Норману в нашей группе»
была физически невыполнима — Боб отвечал в личку (эпизоды 3088 / 3091). Здесь живёт
ОДИН вопрос, отделённый от транспорта и от модели:

* :class:`KnownDestination` — один адрес, который Боб действительно знает: чат, форум-топик
  и человеческая метка, плюс его :class:`DestinationKind` (комната / личка owner'а).
* :func:`resolve_destination` — вердикт: точный адрес, «переспроси» или «не отправляй».

🔴 Решение owner'а: **при неоднозначности переспрашивать, а не угадывать.** Угаданный не
тот адресат — ровно тот класс ошибки, из-за которого заведён эпик, поэтому и «мест такого
рода известно несколько», и «такого места я не знаю» дают ОДИН исход — вопрос. Второе
решение (урок BOB-076): писать в другой чат Боб вправе ТОЛЬКО по просьбе owner'а, и эта
проверка идёт первой — однозначность адреса её не отменяет.

«Это тот же чат» распознаётся СТРУКТУРНО, по совпадению ``chat_id`` с текущим ходом: ядро
не знает слова «здесь» и не должно — иначе оно начнёт угадывать по формулировке.

Чисто и детерминированно (никакого I/O, одинаковый вход → одинаковый вердикт), поэтому и
политика, и её граничные случаи проверяются без транспорта и без модели.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DestinationKind",
    "DestinationOutcome",
    "DestinationVerdict",
    "KnownDestination",
    "resolve_destination",
]


class DestinationKind(Enum):
    """Какого рода место: общая комната или личка owner'а."""

    GROUP = "group"
    OWNER_DM = "owner_dm"


# Как называют место в запросе. Это РАЗБОР закрытого перечня, который модель выбирает
# (тот же приём, что у ``parse_disclosure_consent``), а не угадывание адреса: синоним
# уточняет РОД места, но никогда не выбирает между двумя конкретными чатами.
_ALIASES: dict[str, DestinationKind] = {
    "group": DestinationKind.GROUP,
    "группа": DestinationKind.GROUP,
    "группу": DestinationKind.GROUP,
    "owner_dm": DestinationKind.OWNER_DM,
    "dm": DestinationKind.OWNER_DM,
    "личка": DestinationKind.OWNER_DM,
    "личку": DestinationKind.OWNER_DM,
}


class DestinationOutcome(Enum):
    """Чем кончился разбор адреса: отправляем, переспрашиваем или не отправляем."""

    RESOLVED = "resolved"
    ASK = "ask"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class KnownDestination:
    """Один адрес, который Боб знает: чат + форум-топик + метка для человека."""

    chat_id: int
    topic_id: int | None
    label: str
    kind: DestinationKind


@dataclass(frozen=True, slots=True)
class DestinationVerdict:
    """Вердикт о месте: куда (если решено) и что сказать себе, если нет.

    ``note`` — короткая подсказка ДЛЯ БОБА (не готовая реплика человеку): она объясняет,
    почему отправка не состоялась, чтобы он переспросил или отказал своими словами.
    Пустая у решённого адреса.
    """

    outcome: DestinationOutcome
    address: KnownDestination | None = None
    note: str = ""


_NOT_OWNER = (
    "Не отправляй. Писать в другой чат можно только по просьбе Вовы — "
    "этот человек такого распоряжения дать не может."
)
_ALREADY_HERE = "Не отправляй: это тот же чат, где вы сейчас говорите. Ответь здесь."
_WHICH_PLACE = "Не отправляй. Переспроси, в какой именно чат написать."


def resolve_destination(
    place: str,
    known: Sequence[KnownDestination],
    *,
    from_owner: bool,
    here_chat_id: int,
) -> DestinationVerdict:
    """Решить, куда уходит сообщение — или что переспросить (чисто, BOB-090.B2).

    Порядок проверок и есть политика:

    1. **Не owner** → :attr:`DestinationOutcome.REFUSED`. Однозначность адреса этого не
       отменяет: инициатива писать в чужие чаты принадлежит только owner'у (BOB-076).
    2. Род места не разобран (пусто, мусор, незнакомое название) → :attr:`ASK`.
    3. Ровно один известный адрес такого рода → :attr:`RESOLVED` с ТОЧНЫМ адресом
       (чат и топик). Ноль или несколько → :attr:`ASK`: «несколько» перечисляет метки,
       чтобы вопрос был предметным, «ноль» честно означает «я такого чата не знаю».
    4. Решённый адрес совпал с текущим чатом → :attr:`REFUSED`: отправлять себе же нечего,
       это обычный ответ. Признак структурный (``chat_id``), не словесный.
    """
    if not from_owner:
        return DestinationVerdict(DestinationOutcome.REFUSED, note=_NOT_OWNER)
    kind = _ALIASES.get(place.strip().casefold())
    if kind is None:
        return DestinationVerdict(DestinationOutcome.ASK, note=_WHICH_PLACE)
    candidates = [destination for destination in known if destination.kind is kind]
    if len(candidates) != 1:
        return DestinationVerdict(DestinationOutcome.ASK, note=_ask_note(candidates))
    address = candidates[0]
    if address.chat_id == here_chat_id:
        return DestinationVerdict(DestinationOutcome.REFUSED, note=_ALREADY_HERE)
    return DestinationVerdict(DestinationOutcome.RESOLVED, address=address)


def _ask_note(candidates: Sequence[KnownDestination]) -> str:
    """Подсказка для вопроса: с перечнем меток, когда есть из чего выбирать."""
    if not candidates:
        return _WHICH_PLACE
    labels = ", ".join(destination.label for destination in candidates)
    return f"{_WHICH_PLACE} Известные: {labels}."
