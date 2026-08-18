# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""Переговоры о разрешении — висящий вопрос «упёрся в запрет, разрешаешь?» (срез 3).

ОДНА ответственность: удержать ОДИН заданный владельцу вопрос про разрешение и честно
разрешить его следующим ходом — разрешено, отказано или вопрос снят. Ни спавна, ни
доразрешения, ни знания о ``claude``: повторным заходом занимается менеджер живого сеанса
(:class:`~bob.interactive.usecases.session.InteractiveSessionManager`).

Устроено ровно как :class:`~bob.interactive.resume_negotiation.ResumeNegotiation`, и
намеренно: правила висящего вопроса у Боба одни и те же, а второй их диалект был бы
лишней сущностью в голове владельца. Все три — предохранители, не удобства:

* вопрос ОДИН: новый вытесняет прежний (двух «разрешаешь?» одновременно не бывает);
* вопрос АДРЕСНЫЙ: отвечает только тот, кому задали;
* вопрос НЕ ЗАЛИПАЕТ: любой ход спрашиваемого его снимает, поэтому «да», сказанное потом
  совсем по другому поводу, ничего не запустит.

🔴 Отличие от «поднимаю?» одно, и оно осознанное: окно ответа :data:`PERMISSION_TTL`
ДЛИННЕЕ пятиминутного :data:`~bob.interactive.resume_policy.CONFIRMATION_TTL`. Там вопрос
задан в ответ на просьбу владельца, и он у телефона; здесь вопрос застаёт его врасплох —
конвейер упёрся сам, посреди волны, — и всё это время работа СТОИТ. Бессрочным окно при
этом не становится: «да», пришедшее через час, не смеет запустить необратимое.

🔴 И унаследованная узость «да» (:func:`~bob.interactive.intent.is_confirmation`) здесь
тем более к месту: разрешение исполняет НЕОБРАТИМОЕ, поэтому «да, но сначала покажи
дифф» — не «да». Вопрос снимается, реплика идёт обычным путём, а Боб не додумывает.

I/O-free и детерминированно: часы инъектируются, разбор реплики — чистые предикаты.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta  # runtime-needed: модульная константа — timedelta
from typing import TYPE_CHECKING

from bob.interactive.intent import is_confirmation, is_rejection
from bob.interactive.resume_policy import is_confirmation_fresh

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Protocol

    class _Clock(Protocol):
        """Часы, которые нужны переговорам (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


__all__ = [
    "PERMISSION_TTL",
    "PermissionAnswer",
    "PermissionGranted",
    "PermissionNegotiation",
    "PermissionRefused",
]

#: Сколько живёт вопрос «разрешаешь?». Полчаса: владелец не сидит у телефона, а работа
#: всё это время стоит — но и бессрочным разрешение на необратимое быть не может.
PERMISSION_TTL = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class _PendingPermission:
    """Висящий вопрос: чей он, про какую команду, из какого сеанса и когда задан."""

    command: str
    sender: int | None
    session_id: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class PermissionGranted:
    """Владелец разрешил — вот КАКУЮ команду и в КАКОМ сеансе он разрешил.

    ``session_id`` — сеанс, который спрашивал: между вопросом и ответом он мог смениться,
    и разрешение относится к тому, а не к тому, что случайно живёт сейчас.
    """

    command: str
    session_id: str


@dataclass(frozen=True, slots=True)
class PermissionRefused:
    """Владелец отказал — Боб идёт дальше без этого шага."""


#: Исход разрешения вопроса. ``None`` (в возвращаемом типе :meth:`PermissionNegotiation.
#: settle`) означает «ход к разрешению не относится — веди его обычным путём».
PermissionAnswer = PermissionGranted | PermissionRefused


class PermissionNegotiation:
    """Один висящий вопрос «разрешаешь?» и его честное разрешение следующим ходом."""

    def __init__(self, *, clock: _Clock) -> None:
        self._clock = clock
        self._pending: _PendingPermission | None = None

    def ask(self, *, command: str, sender: int | None, session_id: str) -> None:
        """Взвести вопрос про ``command`` из сеанса ``session_id`` (вытесняет прежний)."""
        self._pending = _PendingPermission(
            command=command,
            sender=sender,
            session_id=session_id,
            requested_at=self._clock.now(),
        )

    def is_pending(self) -> bool:
        """Висит ли сейчас незакрытый вопрос (дёшево, без побочных эффектов)."""
        return self._pending is not None

    def settle(self, text: str, sender: int | None) -> PermissionAnswer | None:
        """Разрешить висящий вопрос ходом ``sender``; ``None`` — «ход не про это».

        ``None`` возвращается, когда вопроса нет, отвечает не тот, кому задали, ответ
        опоздал (:data:`PERMISSION_TTL`) или это не явное «да» и не явное «нет». 🔴 Во
        всех случаях, кроме чужого ответа, вопрос при этом СНИМАЕТСЯ — он не залипает.
        """
        pending = self._pending
        if pending is None:
            return None
        if pending.sender != sender:
            return None  # чужой ответ не снимает и не разрешает вопрос владельца
        self._pending = None
        if not is_confirmation_fresh(
            requested_at=pending.requested_at,
            now=self._clock.now(),
            ttl=PERMISSION_TTL,
        ):
            return None
        if is_confirmation(text):
            return PermissionGranted(
                command=pending.command, session_id=pending.session_id
            )
        if is_rejection(text):
            return PermissionRefused()
        return None
