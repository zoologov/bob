# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Русские слова Боба о простое — один дом на три места (BOB-116, ревью M3, bob-i83.20).

Сообщение владельцу, эпизод «я молчал» и GUPPI ``/status`` раньше несли каждый свой
плюрализатор, свои месяцы, свой период и свою таблицу причин, и копии разошлись («со 2
октября» в автобиографии против «с 2 октября» у владельца). Здесь проверяются сами формы:
склонение, месяц, период с предлогом, длительность в винительном падеже, говорящий по id
провайдера и причина отказа во всех трёх регистрах. Таблицы модульного уровня mutmut не
мутирует, поэтому каждая строка таблиц прибита здесь дословно.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from bob.kernel.provider_health import TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1
from bob.kernel.ru_text import (
    Speaker,
    duration,
    failure_now,
    failure_report,
    failure_then,
    period,
    plural,
    provider_speaker,
)

_MSK = timezone(timedelta(hours=3))
_DAYS = ("день", "дня", "дней")

# --- склонение с числительным -------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "form"),
    [
        (0, "дней"),
        (1, "день"),
        (2, "дня"),
        (3, "дня"),
        (4, "дня"),
        (5, "дней"),
        (10, "дней"),
        (11, "дней"),
        (12, "дней"),
        (13, "дней"),
        (14, "дней"),
        (15, "дней"),
        (20, "дней"),
        (21, "день"),
        (22, "дня"),
        (24, "дня"),
        (25, "дней"),
        (101, "день"),
        (111, "дней"),
        (112, "дней"),
        (114, "дней"),
        (121, "день"),
        (1011, "дней"),
    ],
)
def test_plural_agrees_with_the_number(count: int, form: str) -> None:
    assert plural(count, _DAYS) == form


# --- длительность: винительный падеж ------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (-5, "меньше секунды"),
        (0, "меньше секунды"),
        (0.2, "меньше секунды"),
        (0.999, "меньше секунды"),
        (1, "секунду"),
        (2, "2 секунды"),
        (21, "21 секунду"),
        (40, "40 секунд"),
        (59, "59 секунд"),
        (59.9, "59 секунд"),
        (60, "минуту"),
        (119, "минуту"),
        (120, "2 минуты"),
        (180, "3 минуты"),
        (600, "10 минут"),
        (11 * 60, "11 минут"),
        (21 * 60, "21 минуту"),
        (3599, "59 минут"),
        (3600, "час"),
        (3600 + 60, "1 час 1 минуту"),
        (3600 + 10 * 60, "1 час 10 минут"),
        (2 * 3600 + 15 * 60, "2 часа 15 минут"),
        (6 * 3600, "6 часов"),
        (21 * 3600, "21 час"),
        (22 * 3600, "22 часа"),
        (23 * 3600 + 59 * 60 + 59, "23 часа 59 минут"),
        (86400, "день"),
        (86400 + 3600, "1 день 1 час"),
        (86400 + 5 * 60, "день"),
        (2 * 86400 + 5 * 60, "2 дня"),
        (2 * 86400 + 4 * 3600, "2 дня 4 часа"),
        (9 * 86400 + 23 * 3600 + 32 * 60, "9 дней 23 часа"),
        (11 * 86400, "11 дней"),
        (21 * 86400, "21 день"),
        (112 * 86400, "112 дней"),
    ],
)
def test_duration_reads_as_russian_accusative(seconds: float, expected: str) -> None:
    assert duration(seconds) == expected


# --- период: дата, часы, смещение и предлог ----------------------------------------


def test_period_within_one_day_names_the_day_once() -> None:
    since = datetime(2026, 10, 1, 6, 10, tzinfo=_MSK)
    assert period(since, since + timedelta(minutes=32)) == "1 октября с 06:10 по 06:42 +03:00"


def test_period_across_days_names_both_days() -> None:
    since = datetime(2026, 10, 1, 6, 10, tzinfo=_MSK)
    until = datetime(2026, 10, 10, 6, 42, tzinfo=_MSK)
    assert period(since, until) == "с 1 октября 06:10 по 10 октября 06:42 +03:00"


@pytest.mark.parametrize(
    ("day", "preposition"),
    [
        (1, "с"),
        (2, "со"),  # «со второго» — норма перед «вт»
        (3, "с"),
        (12, "с"),  # «с двенадцатого»
        (20, "с"),
        (22, "с"),  # «с двадцать второго»
        (31, "с"),
    ],
)
def test_period_preposition_is_so_only_before_the_second(day: int, preposition: str) -> None:
    since = datetime(2026, 1, day, 9, 5, tzinfo=_MSK)
    until = since + timedelta(days=1)
    expected = f"{preposition} {day} января 09:05 по {until.day} {_month(until)} 09:05 +03:00"
    assert period(since, until) == expected


def _month(moment: datetime) -> str:
    return "января" if moment.month == 1 else "февраля"


def test_period_within_the_second_day_keeps_s_before_the_clock() -> None:
    # Предлог стоит перед часами («с двух»), а не перед «вторым» — «со» здесь неуместно.
    since = datetime(2026, 10, 2, 2, 10, tzinfo=_MSK)
    assert period(since, since + timedelta(minutes=5)) == "2 октября с 02:10 по 02:15 +03:00"


@pytest.mark.parametrize(
    ("month", "genitive"),
    [
        (1, "января"),
        (2, "февраля"),
        (3, "марта"),
        (4, "апреля"),
        (5, "мая"),
        (6, "июня"),
        (7, "июля"),
        (8, "августа"),
        (9, "сентября"),
        (10, "октября"),
        (11, "ноября"),
        (12, "декабря"),
    ],
)
def test_month_is_in_russian_genitive(month: int, genitive: str) -> None:
    since = datetime(2026, month, 5, 7, 0, tzinfo=_MSK)
    assert period(since, since + timedelta(hours=1)).startswith(f"5 {genitive} с 07:00 ")


def test_period_across_years_carries_both_years() -> None:
    since = datetime(2026, 12, 31, 23, 50, tzinfo=_MSK)
    until = datetime(2027, 1, 1, 0, 5, tzinfo=_MSK)
    assert period(since, until) == "с 31 декабря 2026 23:50 по 1 января 2027 00:05 +03:00"


def test_period_across_days_of_one_year_carries_no_year() -> None:
    since = datetime(2026, 12, 30, 23, 50, tzinfo=_MSK)
    until = datetime(2026, 12, 31, 0, 5, tzinfo=_MSK)
    assert period(since, until) == "с 30 декабря 23:50 по 31 декабря 00:05 +03:00"


@pytest.mark.parametrize(
    ("tz", "label"),
    [
        (UTC, "+00:00"),
        (timezone(timedelta(hours=5, minutes=45)), "+05:45"),
        (timezone(-timedelta(hours=9, minutes=30)), "-09:30"),
    ],
)
def test_period_is_signed_with_the_offset_of_its_end(tz: timezone, label: str) -> None:
    since = datetime(2026, 10, 1, 6, 10, tzinfo=tz)
    assert period(since, since + timedelta(minutes=32)).endswith(f"по 06:42 {label}")


def test_naive_period_carries_no_offset() -> None:
    since = datetime(2026, 10, 1, 6, 10)  # noqa: DTZ001 - наивное время — предмет теста
    assert period(since, since + timedelta(minutes=5)) == "1 октября с 06:10 по 06:15"


def test_clock_pads_hours_and_minutes() -> None:
    since = datetime(2026, 10, 1, 0, 5, tzinfo=_MSK)
    assert period(since, since + timedelta(hours=9)) == "1 октября с 00:05 по 09:05 +03:00"


# --- говорящий по id провайдера ----------------------------------------------------


@pytest.mark.parametrize(
    ("provider_id", "speaker"),
    [
        (TIER0_PRIMARY, Speaker(nominative="облако", genitive="облака", past_ending="о")),
        (TIER0_UNDERSTUDY, Speaker(nominative="дублёр", genitive="дублёра", past_ending="")),
        (
            TIER1,
            Speaker(nominative="основная модель", genitive="основной модели", past_ending="а"),
        ),
        (
            "tier9",
            Speaker(nominative="провайдер tier9", genitive="провайдера tier9", past_ending=""),
        ),
    ],
)
def test_provider_speaker_names_who_fails(provider_id: str, speaker: Speaker) -> None:
    assert provider_speaker(provider_id) == speaker


def test_provider_ids_are_the_ones_the_monitor_reports() -> None:
    reported = (TIER0_PRIMARY, TIER0_UNDERSTUDY, TIER1)
    assert reported == ("tier0-primary", "tier0-understudy", "tier1")


# --- причина отказа: три регистра одной таблицы ------------------------------------

_CLOUD = provider_speaker(TIER0_PRIMARY)
_UNDERSTUDY = provider_speaker(TIER0_UNDERSTUDY)
_MAIN = provider_speaker(TIER1)


@pytest.mark.parametrize(
    ("failure_class", "now"),
    [
        ("auth", "облако отказывает мне в доступе (401/403 — ключ или квота)"),
        ("rate", "облако просит подождать (429 — лимит запросов)"),
        ("server", "облако отвечает ошибкой сервера (5xx)"),
        ("timeout", "облако не отвечает вовремя (таймаут)"),
        ("connection", "до облака не достучаться (соединение)"),
        ("shape", "облако обрывает ответ на полуслове"),
        ("contract", "облако отвергает мой запрос (4xx — похоже, ошибка в настройке)"),
        (None, "облако не работает"),
        ("", "облако не работает"),
        ("teapot", "облако не работает (teapot)"),
    ],
)
def test_failure_now_is_present_tense_with_the_code(failure_class: str | None, now: str) -> None:
    assert failure_now(failure_class, _CLOUD) == now


@pytest.mark.parametrize(
    ("failure_class", "then"),
    [
        ("auth", "облако не пускало меня по ключу/квоте"),
        ("rate", "облако просило меня подождать"),
        ("server", "облако падало на своей стороне"),
        ("timeout", "облако не отвечало"),
        ("connection", "до облака было не достучаться"),
        ("shape", "облако обрывало ответ на полуслове"),
        ("contract", "облако отвергало мой запрос"),
        (None, "облако не работало"),
        ("", "облако не работало"),
        ("teapot", "облако не работало (teapot)"),
    ],
)
def test_failure_then_is_bobs_past_in_the_first_person(
    failure_class: str | None, then: str
) -> None:
    assert failure_then(failure_class, _CLOUD) == then


@pytest.mark.parametrize(
    ("speaker", "then"),
    [
        (_UNDERSTUDY, "дублёр не пускал меня по ключу/квоте"),
        (_MAIN, "основная модель не пускала меня по ключу/квоте"),
    ],
)
def test_failure_then_agrees_with_the_speaker(speaker: Speaker, then: str) -> None:
    assert failure_then("auth", speaker) == then


def test_failure_connection_takes_the_genitive_of_the_speaker() -> None:
    assert failure_then("connection", _UNDERSTUDY) == "до дублёра было не достучаться"
    assert failure_now("connection", _MAIN) == "до основной модели не достучаться (соединение)"


@pytest.mark.parametrize(
    ("failure_class", "report"),
    [
        ("auth", "не пускало по ключу/квоте"),
        ("rate", "просило подождать"),
        ("server", "падало на своей стороне"),
        ("timeout", "не отвечало"),
        ("connection", "до него было не достучаться"),
        ("shape", "обрывало ответ на полуслове"),
        ("contract", "отвергало запрос"),
        (None, "не работало"),
        ("teapot", "не работало (teapot)"),
    ],
)
def test_failure_report_is_impersonal(failure_class: str | None, report: str) -> None:
    # Строка /status уже названа провайдером: причина — безличная, без подлежащего и «меня».
    assert failure_report(failure_class) == report


@pytest.mark.parametrize(
    "failure_class", ["auth", "rate", "server", "timeout", "connection", "shape", "contract"]
)
def test_bobs_memory_and_the_status_carry_no_http_jargon(failure_class: str) -> None:
    for text in (failure_then(failure_class, _CLOUD), failure_report(failure_class)):
        for jargon in ("401", "403", "429", "4xx", "5xx", "HTTP", failure_class):
            assert jargon not in text
