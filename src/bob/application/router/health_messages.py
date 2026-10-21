# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""Что Боб пишет владельцу о здоровье своих LLM-провайдеров (BOB-116).

ОДНА ответственность: превратить факты перехода (кто сломался, чем, сколько и в какой
ситуации) в живую фразу от первого лица по-русски. Без LLM — путь сигнала не должен
зависеть от того, что сломалось (решение владельца Р2). Решение, КАКАЯ это ситуация и
КОГДА слать, принимает монитор (:mod:`bob.application.router.health_monitor`); здесь
только слова.

Ситуации (:class:`Situation`) различают то, что для владельца — разные новости:
«думать нечем», «облако мертво, но держусь на дублёре», «сломан сам дублёр, облако
живо», «не отвечает основная модель разговора» — и тогда своим я не отвечаю вовсе, а гостям
отвечаю облаком попроще. Длительности — в винительном падеже
(«уже минуту», «через час», «молчал 9 дней 23 часа»): все места, где они звучат,
требуют именно его.

Время владельцу — в **поясе процесса** с явным смещением («1 октября с 06:10 до 06:42
+03:00»), как в GUPPI ``/status`` и в эпизоде «я молчал» (решение координатора, bob-i83.15;
один пояс на все три места держит :mod:`bob.kernel.local_time`). Часы Боба идут в UTC,
поэтому момент переводится, а не печатается как пришёл; ``tz`` у :func:`recovered_text` —
только для тестов, сборка его не передаёт. Наивное время печатается как есть и без смещения.

Слова, общие с автобиографией и ``/status``, — склонение, длительность, период, говорящий по
id провайдера и причина отказа — берутся из :mod:`bob.kernel.ru_text` (ревью M3,
bob-i83.20): здесь своих копий нет, только фразы, которые звучат лишь владельцу.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from bob.kernel.local_time import in_local_zone
from bob.kernel.provider_health import TIER0_UNDERSTUDY
from bob.kernel.ru_text import duration, failure_now, period, plural, provider_speaker

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

__all__ = [
    "HealthNotice",
    "Situation",
    "degraded_text",
    "recovered_text",
    "reminder_text",
    "understudy_missing_text",
]


class Situation(Enum):
    """Что переход значит для Боба — от этого зависят слова, а не от кода ошибки."""

    MUTE = "mute"  # думать нечем: облако Tier-0 лежит, а дублёра нет или он тоже лежит
    UNDERSTUDY_HOLDS = "understudy_holds"  # облако Tier-0 лежит, служебное держит дублёр
    UNDERSTUDY_DOWN = "understudy_down"  # лежит сам дублёр, облако Tier-0 живо
    VOICE_DOWN = "voice_down"  # не отвечает основная модель разговора (Tier-1)
    OTHER = "other"  # провайдер, которого монитор не знает по имени


@dataclass(frozen=True, slots=True)
class HealthNotice:
    """Факты одного перехода — вход для всех трёх текстов.

    ``since`` — начало серии отказов, ``now`` — момент перехода (для восстановления —
    первый успех). ``next_reminder_s`` — через сколько будет следующее напоминание,
    ``probe_s`` — как часто пробую провайдера после деградации.
    """

    provider_id: str
    situation: Situation
    failure_class: str | None
    failures: int
    since: datetime
    now: datetime
    next_reminder_s: float
    probe_s: float
    has_understudy: bool
    owner_name: str | None = None


_REQUEST_FORMS = ("запрос", "запроса", "запросов")


def _addressed(owner_name: str | None, sentence: str) -> str:
    """«Вова, я …» с именем; без имени — то же предложение с заглавной буквы."""
    name = (owner_name or "").strip()
    if name:
        return f"{name}, {sentence}"
    return sentence[:1].upper() + sentence[1:]


def _streak(notice: HealthNotice) -> str:
    """«<причина> уже 3 минуты, 5 запросов подряд»."""
    elapsed = duration((notice.now - notice.since).total_seconds())
    count = f"{notice.failures} {plural(notice.failures, _REQUEST_FORMS)}"
    cause = failure_now(notice.failure_class, provider_speaker(notice.provider_id))
    return f"{cause} уже {elapsed}, {count} подряд"


def _remind_later(notice: HealthNotice) -> str:
    return f"Напомню через {duration(notice.next_reminder_s)}, если не пройдёт."


def degraded_text(notice: HealthNotice) -> str:
    """Первый сигнал: провайдер признан неработающим."""
    streak = _streak(notice)
    probe = duration(notice.probe_s)
    remind = _remind_later(notice)
    match notice.situation:
        case Situation.MUTE:
            sentence = f"я не могу думать: {streak}{_mute_company(notice)}"
            sentence += f" я помолчу и буду пробовать раз в {probe}, потом реже. {remind}"
        case Situation.UNDERSTUDY_HOLDS:
            sentence = (
                f"{streak}. Пока держусь на дублёре: он слабее, но думать есть чем. "
                f"Только облако надо чинить, пока дублёр жив. {remind}"
            )
        case Situation.UNDERSTUDY_DOWN:
            sentence = (
                f"{streak}. Пока облако работает, это не страшно, но если оно откажет — "
                f"подстраховать будет некому. {remind}"
            )
        case Situation.VOICE_DOWN:
            sentence = f"{streak}. {_VOICE_DOWN_CONSEQUENCE} {remind}"
        case Situation.OTHER:
            sentence = f"{streak}. {remind}"
    return _addressed(notice.owner_name, sentence)


def _mute_company(notice: HealthNotice) -> str:
    """Хвост первой фразы «думать нечем»: есть ли дублёр и что с ним — и точка с тире."""
    if notice.provider_id == TIER0_UNDERSTUDY:
        return ", а облако тоже лежит —"
    if notice.has_understudy:
        return ", и дублёр тоже не выручает —"
    return ". Дублёра на этой машине нет —"


# Что отказ основной модели значит на деле (ревью N2, bob-i83.24). Ход владельца и любого
# не-гостя идёт через инструменты (ToolLoop) прямо к Tier-1, без отступления на Tier-0, и
# кончается уведомлением GUPPI «Боб временно недоступен». Ход гостя идёт через роутер, который
# при отказе Tier-1 спускается на облако Tier-0, — гостю отвечаю слабее, но сам, пока облако
# живо (``llm_router._rescue_tier``; S14 в ``llm_health.feature``). «Говорить в полную силу не
# могу» здесь было неправдой: получал его ровно тот, кому Боб не отвечал вовсе.
_VOICE_DOWN_CONSEQUENCE = (
    "Тебе и команде я сейчас ответить не могу — вместо меня GUPPI пишет, что я недоступен. "
    "Гостям отвечаю облаком попроще, пока оно живо. Основную модель надо чинить."
)


_REMINDER_OPENINGS = {
    Situation.MUTE: "я всё ещё не могу думать",
    Situation.UNDERSTUDY_HOLDS: "я всё ещё держусь на дублёре",
    Situation.UNDERSTUDY_DOWN: "дублёр всё ещё не работает",
    Situation.VOICE_DOWN: "я всё ещё не могу ответить ни тебе, ни команде",
}


def reminder_text(notice: HealthNotice) -> str:
    """Напоминание по расписанию: всё ещё сломано, сколько, когда напомню снова."""
    speaker = provider_speaker(notice.provider_id)
    opening = _REMINDER_OPENINGS.get(notice.situation, f"{speaker.nominative} всё ещё не работает")
    sentence = f"{opening}: {_streak(notice)}. {_remind_later(notice)}"
    return _addressed(notice.owner_name, sentence)


def recovered_text(notice: HealthNotice, *, tz: tzinfo | None = None) -> str:
    """«Вернулся»: провайдер снова отвечает; «молчал» — только если думать было нечем.

    Период — в поясе ``tz``; ``None`` — пояс процесса (так зовёт монитор).
    """
    speaker = provider_speaker(notice.provider_id)
    lasted = duration((notice.now - notice.since).total_seconds())
    when = period(in_local_zone(notice.since, tz), in_local_zone(notice.now, tz))
    match notice.situation:
        case Situation.MUTE:
            sentence = (
                f"я вернулся: {speaker.nominative} ответил{speaker.past_ending}. "
                f"Молчал {lasted} ({when})."
            )
        case Situation.UNDERSTUDY_HOLDS:
            sentence = (
                f"{speaker.nominative} снова отвечает. Не работало {lasted} ({when}), "
                f"всё это время служебное держал дублёр."
            )
        case _:
            sentence = (
                f"{speaker.nominative} снова отвечает. "
                f"Не работал{speaker.past_ending} {lasted} ({when})."
            )
    return _addressed(notice.owner_name, sentence)


def understudy_missing_text(reason: str, owner_name: str | None) -> str:
    """Сигнал при старте: дублёр включён, но работать не может — и до перезапуска его нет.

    Честно про границу: сборка снимает дублёр на всё время процесса, поэтому модель,
    скачанная после старта, сама не подхватится.
    """
    sentence = (
        f"я стартовал без дублёра: в конфигурации он включён, но {reason}. "
        f"Если облако откажет, подстраховать будет некому. "
        f"Работаю без дублёра до перезапуска: даже если модель появится, сам я его не подхвачу."
    )
    return _addressed(owner_name, sentence)
