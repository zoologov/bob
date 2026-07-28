# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

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

Floor-по-говорящему (BOB-066 .1): у живого floor=БОБ есть набор ``participants`` — id
тех, чьи безметочные реплики Боб держит как обращённые к нему (кто реально в нити с
Бобом). **Аддитивно**: дефолт ``()`` = legacy-режим — пустой набор поднимает AMBIENT от
ЛЮБОГО участника (ровно поведение BOB-025 до этого среза), поэтому старые
``ConversationFloor(...)`` и строки SQLite остаются валидны. Прямое обращение и ответ
Боба доливают говорящего в набор (dedup, потолок), поворот к другому / распад — сбрасывают
его. Так безметочная реплика УЧАСТНИКА нити продолжает диалог, а реплика ПОСТОРОННЕГО не
перехватывается Бобом ошибочно.

* :class:`FloorHolder` — BOB / OTHER / IDLE.
* :class:`ConversationFloor` — frozen-снимок: держатель, id человека при OTHER, когда
  держателя в последний раз подтвердили (``since``), серия безметочных реплик без участия
  Боба (``idle_streak``) и ``participants`` — набор говорящих живой нити (пусто = legacy).
* :class:`FloorConfig` — тюнинг: ``timeout_seconds`` (тайм-аут floor) и
  ``reset_after_silent`` (распад после стольких безметочных реплик подряд).
* :func:`advance_floor` — чистый переход floor по одному ходу.
* :func:`resolve_addressivity` — поднимает AMBIENT→DIRECTED_TO_BOB, пока floor=БОБ жив И
  говорящий — участник нити (или набор пуст = legacy).
* :func:`is_floor_participant` — держит ли Боб живой floor, в котором говорящий признан.
* :func:`idle_floor` — фабрика дефолтного IDLE-floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

from bob.conversation.addressivity import Addressivity

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "ConversationFloor",
    "FloorConfig",
    "FloorHolder",
    "advance_floor",
    "idle_floor",
    "is_floor_participant",
    "resolve_addressivity",
]

# Дефолтный тайм-аут floor: после стольких секунд без подтверждения держателя floor
# считается распавшимся (≈5 минут — разговор «остыл»).
_DEFAULT_TIMEOUT_SECONDS = 300

# Дефолтный распад по молчанию: после стольких безметочных реплик подряд, на которые
# Боб промолчал, floor распадается в IDLE (> 1, чтобы одна реплика не снимала floor).
_DEFAULT_RESET_AFTER_SILENT = 2

# Потолок набора участников живой нити: тред с Бобом реально держит немного говорящих;
# на переполнении самый старый вытесняется (окно последних активных), чтобы набор не рос
# без предела при долгой групповой нити.
_MAX_PARTICIPANTS = 8


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
    БЕЗ участия Боба (для распада по молчанию); ``participants`` — id говорящих живой
    нити при ``holder=BOB`` (чьи безметочные реплики читаются как обращённые к Бобу).

    ``participants`` **аддитивен** и по умолчанию пуст (``()``): пустой набор = legacy —
    поднимает AMBIENT от любого участника (ровно поведение до BOB-066 .1), так что старые
    конструкции и строки SQLite остаются валидны. Не пуст — поднимается только реплика
    признанного говорящего (или с неизвестным ``sender_id``, fail-safe).
    """

    holder: FloorHolder
    holder_id: int | None
    since: datetime | None
    idle_streak: int
    participants: tuple[int, ...] = ()


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


def _sender_recognized(floor: ConversationFloor, sender_id: int | None) -> bool:
    """Признан ли ``sender_id`` говорящим живой нити Боба (floor-по-говорящему).

    Три случая читают безметочную реплику как продолжение нити:
    * набор ``participants`` пуст — **legacy**: любой участник (поведение до BOB-066 .1);
    * ``sender_id`` неизвестен (``None``) — **fail-safe**: не глушим Боба на «тихом» ходу;
    * ``sender_id`` уже в наборе — говорящий реально в нити с Бобом.
    Иначе (посторонний при непустом наборе) — не признан: Боб не перехватывает чужое.
    """
    if not floor.participants:
        return True
    if sender_id is None:
        return True
    return sender_id in floor.participants


def is_floor_participant(
    floor: ConversationFloor,
    sender_id: int | None,
    *,
    now: datetime,
    config: FloorConfig,
) -> bool:
    """Держит ли Боб ЖИВОЙ floor, в котором ``sender_id`` признан говорящим (BOB-066 .1).

    Чистый предикат «эта реплика — часть живой нити Боба с этим говорящим»: floor=БОБ,
    не истёк по тайм-ауту И говорящий признан (:func:`_sender_recognized`). На нём стоит и
    подъём адресности (:func:`resolve_addressivity`), и хинт ``floor_participant`` для
    рефлексивного read.
    """
    return _is_live_bob_floor(floor, now=now, config=config) and _sender_recognized(
        floor, sender_id
    )


def _with_participant(
    participants: tuple[int, ...], sender_id: int | None
) -> tuple[int, ...]:
    """Долить говорящего в набор нити — dedup + потолок (окно последних активных).

    ``None`` (неизвестный говорящий) и уже присутствующий id не меняют набор. На
    переполнении вытесняется самый старый (срез последних ``_MAX_PARTICIPANTS``), чтобы
    долгая групповая нить не растила набор без предела.
    """
    if sender_id is None or sender_id in participants:
        return participants
    return (*participants, sender_id)[-_MAX_PARTICIPANTS:]


def _bob_floor(
    participants: tuple[int, ...], sender_id: int | None, *, now: datetime
) -> ConversationFloor:
    """Свежий floor=БОБ (since=now, streak=0) с говорящим, долитым в набор нити."""
    return ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=now,
        idle_streak=0,
        participants=_with_participant(participants, sender_id),
    )


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
         нить держит БОБА (``since=now``, набор нити сохраняется), но молчание Боба растит
         ``idle_streak``; при ``idle_streak >= reset_after_silent`` floor распадается в
         ``IDLE``. Если floor НЕ у Боба или истёк — ``IDLE`` (Боб не встревает).

    **Floor-по-говорящему (BOB-066 .1):** на ветках БОБА (ответ Боба / прямое обращение)
    ``sender_id`` доливается в ``participants`` (dedup + потолок) — говорящий признаётся
    участником нити. Поворот к другому (``DIRECTED_TO_OTHER``) и любой распад в ``IDLE``
    **сбрасывают** набор (свежий пустой ``()`` = legacy для следующей нити).
    """
    if bob_replied or addressivity is Addressivity.DIRECTED_TO_BOB:
        return _bob_floor(floor.participants, sender_id, now=now)
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
        participants=floor.participants,  # набор нити переживает тихий ход
    )


def resolve_addressivity(
    per_message: Addressivity,
    floor: ConversationFloor,
    *,
    sender_id: int | None,
    now: datetime,
    config: FloorConfig,
) -> Addressivity:
    """Поднять эффективную адресность по непрерывности floor — чисто (BOB-025/066 .1).

    Если поштучная адресность ``AMBIENT`` И floor держит живой Боб И **говорящий признан
    участником нити** (:func:`is_floor_participant` — набор пуст=legacy / ``sender_id``
    неизвестен / ``sender_id`` в наборе) → **``DIRECTED_TO_BOB``** (безметочная реплика
    участника живой нити Боба читается как обращённая к нему — непрерывность). Иначе
    ``per_message`` как есть: прямое обращение и поворот к другому проходят без изменений,
    ``AMBIENT`` при чужом/распавшемся floor ИЛИ **от постороннего** (не в наборе) остаётся
    ``AMBIENT`` (Боб не перехватывает чужое — цель BOB-023 цела).
    """
    if per_message is Addressivity.AMBIENT and is_floor_participant(
        floor, sender_id, now=now, config=config
    ):
        return Addressivity.DIRECTED_TO_BOB
    return per_message
