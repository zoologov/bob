# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel
# beadloom:layer=domain

"""Русские слова Боба о простое провайдера — один дом (BOB-116, ревью M3, bob-i83.20).

ОДНА ответственность: русские формы, которыми Боб рассказывает о простое LLM-провайдера, —
склонение с числительным, длительность, период с датой и предлогом, кто отказывал и чем.
Ими говорят три места: сообщение владельцу (``application/router/health_messages``), эпизод
«я молчал» (``memory/self_action``) и GUPPI ``/status``
(``infrastructure/telegram/health_status``). До этого модуля у каждого были свои копии, и
они разошлись: автобиография писала «со 2 октября», владелец для того же простоя читал
«с 2 октября». Модуль живёт в ``kernel``, потому что его видят все три слоя, а
``application`` не импортирует ``memory``. Только stdlib.

Отдельно от :mod:`bob.kernel.local_time`: тот решает, в каком поясе называть время и как
подписать смещение, а здесь — какими словами. Период берёт подпись смещения оттуда.

Решения, принятые здесь один раз для всех трёх мест:

* **Предлог «со»** — только перед днём «2» в датах «с … по …»: «со второго» — норма, а
  «с первого», «с двенадцатого», «с двадцать второго» — нет. Перед часами предлог всегда
  «с» («с 02:10» читается «с двух»), поэтому в пределах одного дня выходит
  «2 октября с 02:10 по 02:15».
* **Период в пределах дня называет день**: «1 октября с 06:10 по 06:42 +03:00». Владелец
  может прочесть сообщение назавтра, а эпизод вспоминается через недели.
* **Длительность — в винительном падеже** («молчал минуту», «через час», «уже 21 минуту»):
  все места, где она звучит, требуют именно его. Единица с числом 1 звучит без числа.
* **Причина отказа — одна таблица, три регистра.** У каждого класса отказа
  (``fallback_policy.classify_failure``) в одной записи три формы: настоящее время с кодом
  для владельца («облако отказывает мне в доступе (401/403 — ключ или квота)»), прошедшее
  от первого лица для памяти («облако не пускало меня по ключу/квоте») и безличное для
  строки ``/status``, которая уже названа провайдером («не пускало по ключу/квоте»). Новый
  класс или новая формулировка — правка одной записи. Незнакомый класс называется как есть
  в скобках во всех регистрах: это новый класс, который ещё никто не назвал словами, и
  владелец должен увидеть его имя.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.kernel.local_time import utc_offset_label
from bob.kernel.provider_health import TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "Speaker",
    "duration",
    "failure_now",
    "failure_report",
    "failure_then",
    "period",
    "plural",
    "provider_speaker",
]

# --- склонение с числительным ---------------------------------------------------------

_TEENS = range(11, 15)
_FEW = range(2, 5)
_ONE = 1
_DECIMAL = 10
_CENTURY = 100


def plural(count: int, forms: tuple[str, str, str]) -> str:
    """Форма при числительном: 1/21 — первая, 2–4/22 — вторая, 0/5–20/11–14/111 — третья."""
    one, few, many = forms
    if count % _CENTURY in _TEENS:
        return many
    last = count % _DECIMAL
    if last == _ONE:
        return one
    if last in _FEW:
        return few
    return many


# --- длительность ----------------------------------------------------------------------

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
# Винительный падеж: «уже минуту», «через 2 минуты», «молчал 5 минут».
_DAY_FORMS = ("день", "дня", "дней")
_HOUR_FORMS = ("час", "часа", "часов")
_MINUTE_FORMS = ("минуту", "минуты", "минут")
_SECOND_FORMS = ("секунду", "секунды", "секунд")
_UNDER_A_SECOND = "меньше секунды"
_UNITS_SHOWN = 2  # старшая ненулевая единица и следующая за ней


def duration(seconds: float) -> str:
    """Длительность в винительном падеже: старшая ненулевая единица и следующая, если не ноль.

    Меньше минуты — секундами; меньше секунды (и отрицательное — часы назад) — «меньше
    секунды». Одна единица с числом 1 звучит без числа: «час», «минуту».
    """
    whole = int(seconds)
    if whole < 1:
        return _UNDER_A_SECOND
    if whole < _SECONDS_PER_MINUTE:
        return _units([(whole, _SECOND_FORMS)])
    days, rest = divmod(whole, _SECONDS_PER_DAY)
    hours, rest = divmod(rest, _SECONDS_PER_HOUR)
    minutes = rest // _SECONDS_PER_MINUTE
    units = [(days, _DAY_FORMS), (hours, _HOUR_FORMS), (minutes, _MINUTE_FORMS)]
    first = next(index for index, (count, _) in enumerate(units) if count)
    return _units([unit for unit in units[first : first + _UNITS_SHOWN] if unit[0]])


def _units(shown: list[tuple[int, tuple[str, str, str]]]) -> str:
    """«1 час 10 минут»; одиночное «1 час» — просто «час»."""
    if len(shown) == 1 and shown[0][0] == 1:
        return shown[0][1][0]
    return " ".join(f"{count} {plural(count, forms)}" for count, forms in shown)


# --- период ----------------------------------------------------------------------------

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
# «со 2 октября» («со второго»), но «с 1/3/12/22 октября».
_DAY_TAKING_SO = 2


def period(since: datetime, until: datetime) -> str:
    """Период простоя: «1 октября с 06:10 по 06:42 +03:00» или «с 1 октября 06:10 по …».

    Время печатается так, как его несёт ``datetime``: пояс выбирает вызывающий
    (:func:`bob.kernel.local_time.in_local_zone`). Подпись — смещение конца периода;
    у наивного времени её нет. Год называется, только если начало и конец в разных годах.
    """
    offset = utc_offset_label(until)
    zone = f" {offset}" if offset else ""
    if since.date() == until.date():
        return f"{_date(since)} с {_clock(since)} по {_clock(until)}{zone}"
    with_year = since.year != until.year
    start = f"{_date(since, with_year=with_year)} {_clock(since)}"
    end = f"{_date(until, with_year=with_year)} {_clock(until)}"
    return f"{_from_preposition(since.day)} {start} по {end}{zone}"


def _from_preposition(day: int) -> str:
    """«со» перед «вторым», иначе «с»."""
    return "со" if day == _DAY_TAKING_SO else "с"


def _date(moment: datetime, *, with_year: bool = False) -> str:
    """«1 октября» или «31 декабря 2026»."""
    text = f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]}"
    return f"{text} {moment.year}" if with_year else text


def _clock(moment: datetime) -> str:
    """«06:10»."""
    return f"{moment.hour:02d}:{moment.minute:02d}"


# --- кто отказывал ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Speaker:
    """Кто отказывает — в формах, которых требуют фразы.

    ``past_ending`` — окончание глагола прошедшего времени по роду: «облако ответилО»,
    «дублёр ответил», «модель ответилА».
    """

    nominative: str
    genitive: str
    past_ending: str


_SPEAKERS = {
    TIER0_PRIMARY: Speaker(nominative="облако", genitive="облака", past_ending="о"),
    TIER0_UNDERSTUDY: Speaker(nominative="дублёр", genitive="дублёра", past_ending=""),
    TIER1: Speaker(nominative="основная модель", genitive="основной модели", past_ending="а"),
}
# Безличный «говорящий» строки /status: подлежащего нет, глагол среднего рода.
_IMPERSONAL = Speaker(nominative="", genitive="него", past_ending="о")


def provider_speaker(provider_id: str) -> Speaker:
    """Говорящий по id провайдера монитора; незнакомый — «провайдер <id>», мужской род."""
    known = _SPEAKERS.get(provider_id)
    if known is not None:
        return known
    return Speaker(
        nominative=f"провайдер {provider_id}",
        genitive=f"провайдера {provider_id}",
        past_ending="",
    )


# --- чем отказывал ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _FailureWords:
    """Одна причина в трёх формах.

    Подстановки: ``{s}`` — подлежащее с пробелом (у безличной формы пусто), ``{g}`` —
    говорящий в родительном, ``{e}`` — окончание прошедшего времени, ``{me}`` — « меня»
    в памяти Боба и пусто в безличной строке. ``code`` — что чинить, только для владельца.
    """

    present: str
    past: str
    code: str | None


# Класс отказа (``fallback_policy.classify_failure``) → слова.
_FAILURE_WORDS = {
    "auth": _FailureWords(
        present="{s}отказывает мне в доступе",
        past="{s}не пускал{e}{me} по ключу/квоте",
        code="401/403 — ключ или квота",
    ),
    "rate": _FailureWords(
        present="{s}просит подождать",
        past="{s}просил{e}{me} подождать",
        code="429 — лимит запросов",
    ),
    "server": _FailureWords(
        present="{s}отвечает ошибкой сервера",
        past="{s}падал{e} на своей стороне",
        code="5xx",
    ),
    "timeout": _FailureWords(
        present="{s}не отвечает вовремя",
        past="{s}не отвечал{e}",
        code="таймаут",
    ),
    "connection": _FailureWords(
        present="до {g} не достучаться",
        past="до {g} было не достучаться",
        code="соединение",
    ),
    "shape": _FailureWords(
        present="{s}обрывает ответ на полуслове",
        past="{s}обрывал{e} ответ на полуслове",
        code=None,
    ),
    "contract": _FailureWords(
        present="{s}отвергает мой запрос",
        past="{s}отвергал{e}{my} запрос",
        code="4xx — похоже, ошибка в настройке",
    ),
}
_UNNAMED = _FailureWords(present="{s}не работает", past="{s}не работал{e}", code=None)
_ME = " меня"
_MY = " мой"


def failure_now(failure_class: str | None, speaker: Speaker) -> str:
    """Владельцу, сейчас: «облако отказывает мне в доступе (401/403 — ключ или квота)»."""
    words = _words(failure_class)
    text = _fill(words.present, speaker)
    return _with_note(text, words.code if words is not _UNNAMED else failure_class)


def failure_then(failure_class: str | None, speaker: Speaker) -> str:
    """Память Боба, от первого лица: «облако не пускало меня по ключу/квоте»."""
    words = _words(failure_class)
    text = _fill(words.past, speaker, me=_ME, my=_MY)
    return _with_note(text, failure_class if words is _UNNAMED else None)


def failure_report(failure_class: str | None) -> str:
    """Строке ``/status``, безлично: «не пускало по ключу/квоте»."""
    words = _words(failure_class)
    text = _fill(words.past, _IMPERSONAL)
    return _with_note(text, failure_class if words is _UNNAMED else None)


def _words(failure_class: str | None) -> _FailureWords:
    """Запись таблицы; пустой или незнакомый класс — общая формулировка."""
    if not failure_class:
        return _UNNAMED
    return _FAILURE_WORDS.get(failure_class, _UNNAMED)


def _fill(template: str, speaker: Speaker, *, me: str = "", my: str = "") -> str:
    """Шаблон с говорящим; ``me``/``my`` — объект и притяжательное в памяти Боба, иначе пусто."""
    subject = f"{speaker.nominative} " if speaker.nominative else ""
    return template.format(s=subject, g=speaker.genitive, e=speaker.past_ending, me=me, my=my)


def _with_note(text: str, note: str | None) -> str:
    """`` (<пояснение>)`` после фразы, если оно есть."""
    return f"{text} ({note})" if note else text
