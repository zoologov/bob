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
живо», «не отвечает основная модель разговора». Длительности — в винительном падеже
(«уже минуту», «через час», «молчал 9 дней 23 часа»): все места, где они звучат,
требуют именно его.

Время выводится в том поясе, в котором его несёт ``datetime``, с подписью пояса
(«06:10 UTC»): часы Боба идут в UTC, и подпись честнее молчаливого сдвига. Свой
формат длительности здесь, а не общий с автобиографией (``memory/self_action.py``):
``application`` не импортирует ``memory`` — общий модуль в ``kernel`` был бы
следующим шагом, если формат понадобится третьему месту.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "HealthNotice",
    "Situation",
    "degraded_text",
    "format_duration",
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


@dataclass(frozen=True, slots=True)
class _Speaker:
    """Кто отказывает — в тех формах, которых требуют фразы."""

    nominative: str
    genitive: str
    past_ending: str  # «облако ответилО», «дублёр ответил», «модель ответилА»


_CLOUD = _Speaker(nominative="облако", genitive="облака", past_ending="о")
_UNDERSTUDY = _Speaker(nominative="дублёр", genitive="дублёра", past_ending="")
_MAIN_MODEL = _Speaker(nominative="основная модель", genitive="основной модели", past_ending="а")


def _speaker(provider_id: str) -> _Speaker:
    """Говорящий по id провайдера монитора; неизвестный — по имени, мужской род."""
    if provider_id == "tier0-primary":
        return _CLOUD
    if provider_id == "tier0-understudy":
        return _UNDERSTUDY
    if provider_id == "tier1":
        return _MAIN_MODEL
    return _Speaker(
        nominative=f"провайдер {provider_id}",
        genitive=f"провайдера {provider_id}",
        past_ending="",
    )


# Причина по-человечески, с кодом в скобках — владелец по нему понимает, что чинить.
# {n} — кто отказывает (именительный), {g} — родительный.
_CAUSE_BY_CLASS = {
    "auth": "{n} отказывает мне в доступе (401/403 — ключ или квота)",
    "rate": "{n} просит подождать (429 — лимит запросов)",
    "server": "{n} отвечает ошибкой сервера (5xx)",
    "timeout": "{n} не отвечает вовремя (таймаут)",
    "connection": "до {g} не достучаться (соединение)",
    "shape": "{n} обрывает ответ на полуслове",
    "contract": "{n} отвергает мой запрос (4xx — похоже, ошибка в настройке)",
}
_CAUSE_UNKNOWN = "{n} не работает"


def _cause(provider_id: str, failure_class: str | None) -> str:
    """Причина отказа словами; незнакомый или пустой класс — общая формулировка."""
    speaker = _speaker(provider_id)
    template = _CAUSE_BY_CLASS.get(failure_class or "", _CAUSE_UNKNOWN)
    return template.format(n=speaker.nominative, g=speaker.genitive)


def _addressed(owner_name: str | None, sentence: str) -> str:
    """«Вова, я …» с именем; без имени — то же предложение с заглавной буквы."""
    name = (owner_name or "").strip()
    if name:
        return f"{name}, {sentence}"
    return sentence[:1].upper() + sentence[1:]


def _streak(notice: HealthNotice) -> str:
    """«<причина> уже 3 минуты, 5 запросов подряд»."""
    elapsed = format_duration((notice.now - notice.since).total_seconds())
    count = f"{notice.failures} {_plural(notice.failures, ('запрос', 'запроса', 'запросов'))}"
    return f"{_cause(notice.provider_id, notice.failure_class)} уже {elapsed}, {count} подряд"


def _remind_later(notice: HealthNotice) -> str:
    return f"Напомню через {format_duration(notice.next_reminder_s)}, если не пройдёт."


def degraded_text(notice: HealthNotice) -> str:
    """Первый сигнал: провайдер признан неработающим."""
    streak = _streak(notice)
    probe = format_duration(notice.probe_s)
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
            sentence = (
                f"{streak}. Говорить в полную силу я сейчас не могу. "
                f"Буду пробовать дальше. {remind}"
            )
        case Situation.OTHER:
            sentence = f"{streak}. {remind}"
    return _addressed(notice.owner_name, sentence)


def _mute_company(notice: HealthNotice) -> str:
    """Хвост первой фразы «думать нечем»: есть ли дублёр и что с ним — и точка с тире."""
    if notice.provider_id == "tier0-understudy":
        return ", а облако тоже лежит —"
    if notice.has_understudy:
        return ", и дублёр тоже не выручает —"
    return ". Дублёра на этой машине нет —"


_REMINDER_OPENINGS = {
    Situation.MUTE: "я всё ещё не могу думать",
    Situation.UNDERSTUDY_HOLDS: "я всё ещё держусь на дублёре",
    Situation.UNDERSTUDY_DOWN: "дублёр всё ещё не работает",
    Situation.VOICE_DOWN: "я всё ещё без основной модели",
}


def reminder_text(notice: HealthNotice) -> str:
    """Напоминание по расписанию: всё ещё сломано, сколько, когда напомню снова."""
    opening = _REMINDER_OPENINGS.get(
        notice.situation, f"{_speaker(notice.provider_id).nominative} всё ещё не работает"
    )
    sentence = f"{opening}: {_streak(notice)}. {_remind_later(notice)}"
    return _addressed(notice.owner_name, sentence)


def recovered_text(notice: HealthNotice) -> str:
    """«Вернулся»: провайдер снова отвечает; «молчал» — только если думать было нечем."""
    speaker = _speaker(notice.provider_id)
    lasted = format_duration((notice.now - notice.since).total_seconds())
    period = _period(notice.since, notice.now)
    match notice.situation:
        case Situation.MUTE:
            sentence = (
                f"я вернулся: {speaker.nominative} ответил{speaker.past_ending}. "
                f"Молчал {lasted} ({period})."
            )
        case Situation.UNDERSTUDY_HOLDS:
            sentence = (
                f"{speaker.nominative} снова отвечает. Не работало {lasted} ({period}), "
                f"всё это время служебное держал дублёр."
            )
        case _:
            sentence = (
                f"{speaker.nominative} снова отвечает. "
                f"Не работал{speaker.past_ending} {lasted} ({period})."
            )
    return _addressed(notice.owner_name, sentence)


def understudy_missing_text(reason: str, owner_name: str | None) -> str:
    """Сигнал при старте: дублёр в конфигурации включён, но работать не сможет."""
    sentence = (
        f"я стартовал без дублёра: в конфигурации он включён, но {reason}. "
        f"Если облако откажет, подстраховать будет некому."
    )
    return _addressed(owner_name, sentence)


# --- время и длительность ---------------------------------------------------------

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
# Винительный падеж: «уже минуту», «через 2 минуты», «молчал 5 минут».
_DAY_FORMS = ("день", "дня", "дней")
_HOUR_FORMS = ("час", "часа", "часов")
_MINUTE_FORMS = ("минуту", "минуты", "минут")
_SECOND_FORMS = ("секунду", "секунды", "секунд")

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_duration(seconds: float) -> str:
    """Длительность по-русски: старшая ненулевая единица и следующая, если не ноль.

    Одна единица с числом 1 звучит без числа («через час», «раз в минуту»); меньше
    минуты — секундами; меньше секунды (и отрицательное — часы назад) — «меньше секунды».
    """
    whole = int(seconds)
    if whole < 1:
        return "меньше секунды"
    if whole < _SECONDS_PER_MINUTE:
        return _units([(whole, _SECOND_FORMS)])
    days, rest = divmod(whole, _SECONDS_PER_DAY)
    hours, rest = divmod(rest, _SECONDS_PER_HOUR)
    minutes = rest // _SECONDS_PER_MINUTE
    units = [(days, _DAY_FORMS), (hours, _HOUR_FORMS), (minutes, _MINUTE_FORMS)]
    first = next(index for index, (count, _) in enumerate(units) if count)
    return _units([unit for unit in units[first : first + 2] if unit[0]])


def _units(shown: list[tuple[int, tuple[str, str, str]]]) -> str:
    """«1 час 10 минут»; одиночное «1 час» — просто «час»."""
    if len(shown) == 1 and shown[0][0] == 1:
        return shown[0][1][0]
    return " ".join(f"{count} {_plural(count, forms)}" for count, forms in shown)


def _plural(count: int, forms: tuple[str, str, str]) -> str:
    """Согласование с числительным: 1/21 — первая форма, 2–4/22 — вторая, 5/11–14 — третья."""
    one, few, many = forms
    if count % 100 in range(11, 15):
        return many
    last = count % 10
    if last == 1:
        return one
    if last in range(2, 5):
        return few
    return many


def _period(since: datetime, until: datetime) -> str:
    """«с 06:10 по 06:42 UTC» в пределах дня, иначе «с 1 октября 06:10 по 10 октября 06:42 UTC»."""
    zone = f" {until.tzname()}" if until.tzname() else ""
    if since.date() == until.date():
        return f"с {_clock(since)} по {_clock(until)}{zone}"
    with_year = since.year != until.year
    start = f"{_date(since, with_year=with_year)} {_clock(since)}"
    end = f"{_date(until, with_year=with_year)} {_clock(until)}"
    return f"с {start} по {end}{zone}"


def _date(moment: datetime, *, with_year: bool) -> str:
    text = f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]}"
    return f"{text} {moment.year}" if with_year else text


def _clock(moment: datetime) -> str:
    return f"{moment.hour:02d}:{moment.minute:02d}"
