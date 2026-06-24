# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Conversation floor — кто сейчас «у микрофона» в треде (BOB-025).

Над поштучной адресностью (BOB-023) живёт трекер **разговорной реплики**
(conversational floor): пока floor держит Боб, безметочная ``AMBIENT``-реплика от
ЛЮБОГО участника поднимается до ``DIRECTED_TO_BOB`` (непрерывность диалога — owner и
гость говорят с Бобом без метки в каждом сообщении). Прямое обращение и ответ Боба
«приклеивают» реплику к нему; явный поворот к другому человеку или распад (тайм-аут /
серия безметочных реплик, на которые Боб промолчал) снимают её, возвращая осторожную
ambient-логику BOB-023 (Боб не встревает в чужой диалог).

Модуль — **чистый домен**: без I/O, без рандома, детерминирован по инъектированному
``now`` (часы живут в application). Персист floor — за портом ``ConversationFloorStore``;
интеграция в ход — в ``handle_message`` (отдельный беад).

* :class:`FloorHolder` — BOB / OTHER / IDLE.
* :class:`ConversationFloor` — frozen-снимок: держатель, id человека при OTHER, когда
  держателя в последний раз подтвердили (``since``) и серия безметочных реплик без
  участия Боба (``idle_streak``).
* :class:`FloorConfig` — тюнинг: ``timeout_seconds`` (тайм-аут floor) и
  ``reset_after_silent`` (распад после стольких безметочных реплик подряд).
* :func:`advance_floor` — чистый переход floor по одному ходу.
* :func:`resolve_addressivity` — поднимает AMBIENT→DIRECTED_TO_BOB, пока floor=БОБ жив.
* :func:`idle_floor` — фабрика дефолтного IDLE-floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

from bob.domain.personality.addressivity import Addressivity

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "ConversationFloor",
    "FloorConfig",
    "FloorHolder",
    "advance_floor",
    "idle_floor",
    "resolve_addressivity",
]

# Дефолтный тайм-аут floor: после стольких секунд без подтверждения держателя floor
# считается распавшимся (≈5 минут — разговор «остыл»).
_DEFAULT_TIMEOUT_SECONDS = 300

# Дефолтный распад по молчанию: после стольких безметочных реплик подряд, на которые
# Боб промолчал, floor распадается в IDLE (> 1, чтобы одна реплика не снимала floor).
_DEFAULT_RESET_AFTER_SILENT = 2


class FloorHolder(Enum):
    """Кто сейчас держит разговорную реплику в треде.

    * :data:`BOB` — «у микрофона» Боб: безметочное от любого участника поднимается к
      нему (непрерывность), пока floor жив.
    * :data:`OTHER` — реплику держит другой человек (явный поворот к нему): Боб
      отступает, как в BOB-023.
    * :data:`IDLE` — реплику никто не держит: безметочное остаётся ``AMBIENT`` (Боб
      не встревает в чужое).
    """

    BOB = "bob"
    OTHER = "other"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class ConversationFloor:
    """Снимок разговорной реплики в треде (frozen value object).

    ``holder`` — кто держит floor; ``holder_id`` — id человека при ``OTHER`` (иначе
    ``None``); ``since`` — когда держателя в последний раз подтвердили (для тайм-аута;
    ``None`` при ``IDLE``); ``idle_streak`` — сколько безметочных реплик подряд прошло
    БЕЗ участия Боба (для распада по молчанию).
    """

    holder: FloorHolder
    holder_id: int | None
    since: datetime | None
    idle_streak: int


@dataclass(frozen=True, slots=True)
class FloorConfig:
    """Тюнинг трекера floor (инъекция из ``addressivity.floor.*`` конфига).

    ``timeout_seconds`` — после стольких секунд без подтверждения держателя floor
    считается распавшимся; ``reset_after_silent`` — после стольких безметочных реплик
    подряд, на которые Боб промолчал, floor=БОБ распадается в ``IDLE``. Оба > 0, чтобы
    floor нельзя было сделать мгновенно-распадающимся.
    """

    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    reset_after_silent: int = _DEFAULT_RESET_AFTER_SILENT

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.reset_after_silent <= 0:
            raise ValueError("reset_after_silent must be positive")


def idle_floor() -> ConversationFloor:
    """Дефолтный floor: реплику никто не держит (свежий тред / после распада)."""
    return ConversationFloor(
        holder=FloorHolder.IDLE, holder_id=None, since=None, idle_streak=0
    )


def _is_live_bob_floor(
    floor: ConversationFloor, *, now: datetime, config: FloorConfig
) -> bool:
    """Держит ли Боб floor И не истёк ли он по тайм-ауту (нужен ``since``)."""
    if floor.holder is not FloorHolder.BOB or floor.since is None:
        return False
    timeout = timedelta(seconds=config.timeout_seconds)
    return now - floor.since <= timeout


def advance_floor(
    floor: ConversationFloor,
    *,
    addressivity: Addressivity,
    sender_id: int | None,
    directed_to_id: int | None,
    bob_replied: bool,
    now: datetime,
    config: FloorConfig,
) -> ConversationFloor:
    """Перевести floor по одному ходу — чисто, детерминированно по ``now`` (BOB-025).

    Приоритет (сильный → слабый):

    1. **Боб ответил этим ходом** (``bob_replied``) → ``BOB(since=now, streak=0)``:
       ответ Боба «приклеивает» реплику к нему (US-1/US-2), какой бы ни была адресность.
    2. По :class:`Addressivity`:
       * ``DIRECTED_TO_BOB`` → ``BOB(since=now, streak=0)`` — прямое обращение
         (пере)берёт floor.
       * ``DIRECTED_TO_OTHER`` → ``OTHER(holder_id=directed_to_id, since=now,
         streak=0)`` — явный поворот к другому, Боб отступает.
       * ``AMBIENT`` → если floor=БОБ и жив (``now - since <= timeout``), реплика в
         нить держит БОБА (``since=now``), но молчание Боба растит ``idle_streak``; при
         ``idle_streak >= reset_after_silent`` floor распадается в ``IDLE``. Если floor
         НЕ у Боба или истёк — ``IDLE`` (Боб не встревает).

    ``sender_id`` принимается для будущей гранулярности (кто говорил) и единообразия
    вызова; сейчас на переход не влияет.
    """
    del sender_id  # принимается для единообразия вызова; на переход пока не влияет
    if bob_replied:
        return ConversationFloor(
            holder=FloorHolder.BOB, holder_id=None, since=now, idle_streak=0
        )
    if addressivity is Addressivity.DIRECTED_TO_BOB:
        return ConversationFloor(
            holder=FloorHolder.BOB, holder_id=None, since=now, idle_streak=0
        )
    if addressivity is Addressivity.DIRECTED_TO_OTHER:
        return ConversationFloor(
            holder=FloorHolder.OTHER,
            holder_id=directed_to_id,
            since=now,
            idle_streak=0,
        )
    return _advance_ambient(floor, now=now, config=config)


def _advance_ambient(
    floor: ConversationFloor, *, now: datetime, config: FloorConfig
) -> ConversationFloor:
    """Перевести floor по безметочной (``AMBIENT``) реплике, на которую Боб промолчал.

    Пока floor=БОБ и жив, реплика в нить держит БОБА (рефреш ``since``), но молчание
    Боба растит ``idle_streak`` — на ``reset_after_silent`` floor распадается в
    ``IDLE``. Если floor НЕ у Боба или истёк по тайм-ауту — ``IDLE`` (Боб не лезет).
    """
    if not _is_live_bob_floor(floor, now=now, config=config):
        return idle_floor()
    next_streak = floor.idle_streak + 1
    if next_streak >= config.reset_after_silent:
        return idle_floor()
    return ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=now,
        idle_streak=next_streak,
    )


def resolve_addressivity(
    per_message: Addressivity,
    floor: ConversationFloor,
    *,
    now: datetime,
    config: FloorConfig,
) -> Addressivity:
    """Поднять эффективную адресность по непрерывности floor — чисто (BOB-025).

    Если поштучная адресность ``AMBIENT`` И floor держит Боб И floor жив (не истёк по
    тайм-ауту) → **``DIRECTED_TO_BOB``** (безметочная реплика в живой нити Боба читается
    как обращённая к нему — непрерывность). Иначе ``per_message`` возвращается как есть:
    прямое обращение и явный поворот к другому проходят без изменений, а ``AMBIENT`` при
    чужом/распавшемся floor остаётся ``AMBIENT`` (Боб не перехватывает чужое — цель
    BOB-023 цела).
    """
    if per_message is Addressivity.AMBIENT and _is_live_bob_floor(
        floor, now=now, config=config
    ):
        return Addressivity.DIRECTED_TO_BOB
    return per_message
