# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""Политика возобновления сессии — чистое доменное ядро (BOB-087.D3).

ОДНА ответственность: решить, МОЖНО ли поднять приостановленную работу и КАКУЮ именно.
Два чистых решения этой политики:

* :func:`select_resumable` — выбрать возобновляемую сессию долгоживущего workspace.
  🔴 Кандидат обязан быть ТЕРМИНАЛЬНЫМ (:func:`bob.coding.state.is_terminal` — тот же
  единственный источник правды, что и у стора; ``INTERACTIVE`` и остальные нетерминальные
  исключены по построению). Это СТРУКТУРНАЯ гарантия «никакого live-attach»: поднять
  можно только то, что уже остановлено, поэтому два водителя не могут оказаться за одним
  процессом ``claude``. Кроме терминальности кандидат обязан лежать на ТОЙ ЖЕ ветке и
  нести непустой ``claude_session_id`` (иначе ``--resume`` нечего передать). Из
  оставшихся берётся САМАЯ СВЕЖАЯ по ``updated_at``.
* :func:`is_confirmation_fresh` — не протух ли висящий вопрос-подтверждение. Окно
  :data:`CONFIRMATION_TTL`; «да», пришедшее позже (или на часах, ушедших НАЗАД), сессию
  не поднимает.

I/O-free и детерминированно (mutation-цель): часы и список сессий передаются аргументами.
"""

from __future__ import annotations

from datetime import timedelta  # runtime-needed: the module constants are timedeltas
from typing import TYPE_CHECKING

from bob.coding.state import is_terminal

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from bob.coding.entities import CodingSession

__all__ = ["CONFIRMATION_TTL", "is_confirmation_fresh", "select_resumable"]

#: Сколько живёт заданный owner'у вопрос «поднимаю?» — окно, в котором «да» ещё
#: относится к нему. Коротко нарочно: подтверждение — предохранитель момента, а не
#: бессрочное разрешение.
CONFIRMATION_TTL = timedelta(minutes=5)

#: Минимальный допустимый «возраст» подтверждения. Отрицательный возраст означает, что
#: часы ушли назад; такому подтверждению не доверяем (иначе висящий вопрос стал бы
#: бессмертным), поэтому окно двустороннее.
_MIN_AGE = timedelta(0)


def select_resumable(
    sessions: Iterable[CodingSession], *, branch: str
) -> CodingSession | None:
    """Самая свежая ВОЗОБНОВЛЯЕМАЯ сессия ветки ``branch``, иначе ``None`` (чистая функция).

    Возобновляема сессия, которая одновременно: лежит на ``branch``, несёт непустой
    ``claude_session_id`` и находится в ТЕРМИНАЛЬНОМ состоянии. Среди подходящих
    выигрывает наибольший ``updated_at``; при полном отсутствии кандидатов — ``None``.
    Фильтр применяется ДО сравнения свежести, поэтому более свежая, но неподходящая
    сессия (живая / чужая ветка / без id) не затеняет годного кандидата.
    """
    candidates = [
        session for session in sessions if _is_resumable(session, branch=branch)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda session: session.updated_at)


def _is_resumable(session: CodingSession, *, branch: str) -> bool:
    """Годится ли ``session`` к возобновлению на ``branch`` (три условия сразу)."""
    if session.branch != branch:
        return False
    if not session.claude_session_id:
        return False
    return is_terminal(session.state)


def is_confirmation_fresh(
    *, requested_at: datetime, now: datetime, ttl: timedelta = CONFIRMATION_TTL
) -> bool:
    """Не протух ли вопрос-подтверждение, заданный в ``requested_at`` (чистая функция).

    Окно ДВУСТОРОННЕЕ: возраст ``now - requested_at`` должен лежать между нулём и ``ttl``
    ВКЛЮЧИТЕЛЬНО. Ровно на границе подтверждение ещё принимается; позже — нет.
    Отрицательный возраст (часы ушли назад) считается протухшим: непонятному времени не
    доверяем, а безопасный отказ здесь — «не поднимать».
    """
    age = now - requested_at
    return _MIN_AGE <= age <= ttl
