# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""Переговоры о подъёме приостановленной работы — висящий вопрос «поднимаю?».

ОДНА ответственность: удержать ОДИН заданный owner'у вопрос и честно его разрешить
следующим ходом — подтверждён, отклонён или снят. Ни поиска сессий, ни спавна, ни
персиста: подъёмом занимается менеджер живого сеанса
(:class:`~bob.interactive.usecases.session.InteractiveSessionManager`), а здесь —
только машина самого вопроса.

🔴 BOB-087.E (bob-6u2): раньше это состояние (``_PendingResume`` + TTL + разбор «да»/
«нет» + снятие вопроса) жило прямо в менеджере, и тот держал ДВЕ называемые
ответственности — жизненный цикл живого процесса И переговоры. Разведены. 🔴 Что
НЕ уехало и не уедет: захват живого сеанса (``_claim``) и само поле ``_live`` остались
в менеджере — на их СИНХРОННОМ обмене держится структурная идемпотентность гонки
«процесс умер И owner жмёт стоп», и растащить их по объектам значило бы её разрушить.

Правила вопроса (все три — предохранители, не удобства):

* он ОДИН: новый вопрос вытесняет прежний (двух «поднимаю?» одновременно не бывает);
* он ADRESНЫЙ: отвечать на него может только тот, кому его задали;
* он НЕ ЗАЛИПАЕТ: любой ход спрашиваемого снимает вопрос — даже если это не «да» и не
  «нет». Поэтому «да», сказанное потом совсем по другому поводу, ничего не поднимет.

I/O-free и детерминированно: часы инъектируются, разбор реплики — чистые предикаты
(:mod:`bob.interactive.intent`), окно свежести — чистая политика
(:func:`~bob.interactive.resume_policy.is_confirmation_fresh`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.interactive.intent import is_confirmation, is_rejection
from bob.interactive.resume_policy import is_confirmation_fresh

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Protocol

    class _Clock(Protocol):
        """Часы, которые нужны переговорам (инъектируются для детерминизма тестов)."""

        def now(self) -> datetime: ...


__all__ = ["ResumeAnswer", "ResumeConfirmed", "ResumeNegotiation", "ResumeRejected"]


@dataclass(frozen=True, slots=True)
class _PendingResume:
    """Висящий вопрос «поднимаю?»: чей он, про какой workspace и когда задан."""

    name: str
    sender: int | None
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ResumeConfirmed:
    """Owner подтвердил подъём — и вот КАКОЙ workspace он подтвердил."""

    workspace: str


@dataclass(frozen=True, slots=True)
class ResumeRejected:
    """Owner отказался — поднимать не нужно, работа остаётся лежать как есть."""


#: Исход разрешения вопроса. ``None`` (в возвращаемом типе :meth:`ResumeNegotiation.settle`)
#: означает «ход к возобновлению не относится — веди его обычным путём».
ResumeAnswer = ResumeConfirmed | ResumeRejected


class ResumeNegotiation:
    """Один висящий вопрос «поднимаю?» и его честное разрешение следующим ходом."""

    def __init__(self, *, clock: _Clock) -> None:
        self._clock = clock
        self._pending: _PendingResume | None = None

    def ask(self, *, name: str, sender: int | None) -> None:
        """Взвести вопрос про workspace ``name``, заданный ``sender`` (вытесняет прежний)."""
        self._pending = _PendingResume(
            name=name, sender=sender, requested_at=self._clock.now()
        )

    def is_pending(self) -> bool:
        """Висит ли сейчас незаданный вопрос (дёшево, без побочных эффектов)."""
        return self._pending is not None

    def settle(self, text: str, sender: int | None) -> ResumeAnswer | None:
        """Разрешить висящий вопрос ходом ``sender``; ``None`` — «ход не про это».

        ``None`` возвращается, когда вопроса нет, отвечает НЕ тот, кому его задали,
        подтверждение протухло (см.
        :func:`~bob.interactive.resume_policy.is_confirmation_fresh`) или реплика не
        является ни явным «да», ни явным «нет». 🔴 Во всех случаях, кроме чужого ответа,
        вопрос при этом СНИМАЕТСЯ — он не залипает.
        """
        pending = self._pending
        if pending is None:
            return None
        if pending.sender != sender:
            return None  # чужой ответ не снимает и не подтверждает owner-вопрос
        self._pending = None
        if not is_confirmation_fresh(
            requested_at=pending.requested_at, now=self._clock.now()
        ):
            return None
        if is_confirmation(text):
            return ResumeConfirmed(workspace=pending.name)
        if is_rejection(text):
            return ResumeRejected()
        return None
