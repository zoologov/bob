# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тексты владельцу о здоровье LLM-провайдеров (BOB-116 D3).

Проверяется то, что прочтёт человек: от первого лица, по-русски, без LLM, с обращением по
имени, когда оно есть, и с честной ситуацией — «думать нечем», «держусь на дублёре»,
«дублёр сломан, облако живо», «основная модель не отвечает».
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from bob.application.router.health_messages import (
    HealthNotice,
    Situation,
    degraded_text,
    format_duration,
    recovered_text,
    reminder_text,
    understudy_missing_text,
)

_SINCE = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


def _notice(
    *,
    provider_id: str = "tier0-primary",
    situation: Situation = Situation.MUTE,
    failure_class: str | None = "auth",
    failures: int = 5,
    elapsed: timedelta = timedelta(minutes=3),
    has_understudy: bool = False,
    owner_name: str | None = "Вова",
    next_reminder_s: float = 600.0,
    probe_s: float = 60.0,
) -> HealthNotice:
    return HealthNotice(
        provider_id=provider_id,
        situation=situation,
        failure_class=failure_class,
        failures=failures,
        since=_SINCE,
        now=_SINCE + elapsed,
        next_reminder_s=next_reminder_s,
        probe_s=probe_s,
        has_understudy=has_understudy,
        owner_name=owner_name,
    )


# --- длительность -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.2, "меньше секунды"),
        (1, "секунду"),
        (40, "40 секунд"),
        (60, "минуту"),
        (180, "3 минуты"),
        (600, "10 минут"),
        (21 * 60, "21 минуту"),
        (3600, "час"),
        (3600 + 10 * 60, "1 час 10 минут"),
        (6 * 3600, "6 часов"),
        (86400, "день"),
        (9 * 86400 + 23 * 3600 + 32 * 60, "9 дней 23 часа"),
        (2 * 86400 + 5 * 60, "2 дня"),
        (11 * 86400, "11 дней"),
        (22 * 3600, "22 часа"),
    ],
)
def test_duration_reads_as_russian_accusative(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_negative_duration_is_not_shown_as_negative() -> None:
    assert format_duration(-5) == "меньше секунды"


# --- сигнал о деградации ----------------------------------------------------------


def test_mute_without_understudy_matches_the_approved_wording() -> None:
    text = degraded_text(_notice())
    assert text == (
        "Вова, я не могу думать: облако отказывает мне в доступе (401/403 — ключ или "
        "квота) уже 3 минуты, 5 запросов подряд. Дублёра на этой машине нет — я помолчу "
        "и буду пробовать раз в минуту, потом реже. Напомню через 10 минут, если не пройдёт."
    )


def test_without_owner_name_the_message_starts_with_a_capital() -> None:
    text = degraded_text(_notice(owner_name=None))
    assert text.startswith("Я не могу думать: облако")


def test_blank_owner_name_is_treated_as_no_name() -> None:
    assert degraded_text(_notice(owner_name="  ")).startswith("Я не могу думать")


def test_cloud_dead_while_understudy_holds_says_so() -> None:
    text = degraded_text(_notice(situation=Situation.UNDERSTUDY_HOLDS, has_understudy=True))
    assert text.startswith("Вова, облако отказывает мне в доступе")
    assert "держусь на дублёре" in text
    assert "облако надо чинить" in text
    assert "не могу думать" not in text


def test_both_tier0_providers_down_is_mute_and_names_the_understudy() -> None:
    text = degraded_text(_notice(has_understudy=True))
    assert "я не могу думать" in text
    assert "дублёр тоже не выручает" in text
    assert "Дублёра на этой машине нет" not in text


def test_understudy_going_down_after_the_cloud_is_mute_and_names_the_cloud() -> None:
    text = degraded_text(
        _notice(provider_id="tier0-understudy", has_understudy=True, failure_class="connection")
    )
    assert "я не могу думать: до дублёра не достучаться" in text
    assert "облако тоже лежит" in text


def test_understudy_down_alone_is_not_alarmist() -> None:
    text = degraded_text(
        _notice(
            provider_id="tier0-understudy",
            situation=Situation.UNDERSTUDY_DOWN,
            has_understudy=True,
            failure_class="timeout",
        )
    )
    assert text.startswith("Вова, дублёр не отвечает вовремя (таймаут)")
    assert "подстраховать будет некому" in text
    assert "не могу думать" not in text


def test_voice_tier_down_names_the_main_model() -> None:
    text = degraded_text(
        _notice(provider_id="tier1", situation=Situation.VOICE_DOWN, failure_class="rate")
    )
    assert text.startswith("Вова, основная модель просит подождать (429")
    assert "в полную силу" in text


@pytest.mark.parametrize(
    ("failure_class", "fragment"),
    [
        ("auth", "отказывает мне в доступе (401/403 — ключ или квота)"),
        ("rate", "просит подождать (429 — лимит запросов)"),
        ("server", "отвечает ошибкой сервера (5xx)"),
        ("timeout", "не отвечает вовремя (таймаут)"),
        ("connection", "до облака не достучаться"),
        ("shape", "обрывает ответ на полуслове"),
        ("contract", "отвергает мой запрос"),
        (None, "облако не работает"),
        ("unheard-of", "облако не работает"),
    ],
)
def test_every_failure_class_has_a_human_cause(failure_class: str | None, fragment: str) -> None:
    assert fragment in degraded_text(_notice(failure_class=failure_class))


def test_failure_count_agrees_with_the_number() -> None:
    assert "2 запроса подряд" in degraded_text(_notice(failures=2))
    assert "21 запрос подряд" in degraded_text(_notice(failures=21))


def test_unknown_provider_gets_a_neutral_text() -> None:
    text = degraded_text(_notice(provider_id="tier9", situation=Situation.OTHER))
    assert "провайдер tier9 не работает" not in text  # класс auth — причина названа
    assert "провайдер tier9 отказывает мне в доступе" in text


# --- напоминание ------------------------------------------------------------------


def test_reminder_states_how_long_and_when_next() -> None:
    text = reminder_text(
        _notice(elapsed=timedelta(hours=1, minutes=13), failures=40, next_reminder_s=3600)
    )
    assert text == (
        "Вова, я всё ещё не могу думать: облако отказывает мне в доступе (401/403 — ключ "
        "или квота) уже 1 час 13 минут, 40 запросов подряд. Напомню через час, если не пройдёт."
    )


@pytest.mark.parametrize(
    ("situation", "provider_id", "opening"),
    [
        (Situation.UNDERSTUDY_HOLDS, "tier0-primary", "Вова, я всё ещё держусь на дублёре: "),
        (Situation.UNDERSTUDY_DOWN, "tier0-understudy", "Вова, дублёр всё ещё не работает: "),
        (Situation.VOICE_DOWN, "tier1", "Вова, я всё ещё без основной модели: "),
        (Situation.OTHER, "tier9", "Вова, провайдер tier9 всё ещё не работает: "),
    ],
)
def test_reminder_opening_follows_the_situation(
    situation: Situation, provider_id: str, opening: str
) -> None:
    text = reminder_text(_notice(situation=situation, provider_id=provider_id))
    assert text.startswith(opening)


# --- восстановление ---------------------------------------------------------------


def test_recovered_after_muteness_matches_the_approved_wording() -> None:
    text = recovered_text(
        _notice(owner_name=None, elapsed=timedelta(days=9, hours=23, minutes=32)), tz=UTC
    )
    assert text == (
        "Я вернулся: облако ответило. Молчал 9 дней 23 часа "
        "(с 1 октября 06:10 по 11 октября 05:42 +00:00)."
    )


def test_recovered_within_one_day_shows_only_clock_times() -> None:
    text = recovered_text(_notice(elapsed=timedelta(minutes=32)), tz=UTC)
    assert text.endswith("Молчал 32 минуты (с 06:10 по 06:42 +00:00).")


# Время владельцу — в поясе процесса с явным смещением, без «UTC» (решение координатора,
# bob-i83.15). Два пояса, ни один не UTC: реализация, которая игнорирует ``tz`` или печатает
# пояс часов, краснеет на любой машине — с поясом машины совпадёт максимум один случай.
@pytest.mark.parametrize(
    ("tz", "period"),
    [
        (timezone(timedelta(hours=3)), "(с 09:10 по 09:42 +03:00)"),
        (timezone(-timedelta(hours=9, minutes=30)), "(с 20:40 по 21:12 -09:30)"),
    ],
)
def test_recovered_period_is_told_in_the_given_zone_with_its_offset(
    tz: tzinfo, period: str
) -> None:
    text = recovered_text(_notice(elapsed=timedelta(minutes=32)), tz=tz)
    assert text.endswith(f"Молчал 32 минуты {period}.")
    assert "UTC" not in text


def test_recovered_period_defaults_to_the_process_zone() -> None:
    text = recovered_text(_notice(elapsed=timedelta(minutes=32)))
    local_until = (_SINCE + timedelta(minutes=32)).astimezone()
    zone = local_until.strftime("%z")  # «+0300» — пояс процесса, посчитанный мимо модуля
    assert text.endswith(f"по {local_until:%H:%M} {zone[:3]}:{zone[3:]}).")
    assert "UTC" not in text


def test_recovered_understudy_after_muteness_names_the_understudy() -> None:
    text = recovered_text(_notice(provider_id="tier0-understudy", has_understudy=True))
    assert text.startswith("Вова, я вернулся: дублёр ответил. Молчал 3 минуты")


def test_recovered_cloud_while_understudy_held_is_not_called_silence() -> None:
    text = recovered_text(_notice(situation=Situation.UNDERSTUDY_HOLDS, has_understudy=True))
    assert text.startswith("Вова, облако снова отвечает. Не работало 3 минуты")
    assert "держал дублёр" in text
    assert "Молчал" not in text


@pytest.mark.parametrize(
    ("situation", "provider_id", "opening"),
    [
        (Situation.UNDERSTUDY_DOWN, "tier0-understudy", "Вова, дублёр снова отвечает."),
        (Situation.VOICE_DOWN, "tier1", "Вова, основная модель снова отвечает."),
        (Situation.OTHER, "tier9", "Вова, провайдер tier9 снова отвечает."),
    ],
)
def test_recovered_opening_follows_the_situation(
    situation: Situation, provider_id: str, opening: str
) -> None:
    assert recovered_text(_notice(situation=situation, provider_id=provider_id)).startswith(
        opening
    )


def test_period_across_years_carries_the_years() -> None:
    since = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
    notice = HealthNotice(
        provider_id="tier0-primary",
        situation=Situation.MUTE,
        failure_class="server",
        failures=5,
        since=since,
        now=since + timedelta(hours=2),
        next_reminder_s=600.0,
        probe_s=60.0,
        has_understudy=False,
        owner_name=None,
    )
    assert "(с 31 декабря 2026 23:00 по 1 января 2027 01:00 +00:00)" in recovered_text(
        notice, tz=UTC
    )


def test_naive_times_carry_no_zone_label() -> None:
    since = datetime(2026, 10, 1, 6, 10)  # noqa: DTZ001 — проверяется именно отсутствие пояса
    notice = HealthNotice(
        provider_id="tier0-primary",
        situation=Situation.MUTE,
        failure_class="server",
        failures=5,
        since=since,
        now=since + timedelta(minutes=5),
        next_reminder_s=600.0,
        probe_s=60.0,
        has_understudy=False,
        owner_name=None,
    )
    assert recovered_text(notice, tz=timezone(timedelta(hours=3))).endswith(
        "(с 06:10 по 06:15)."
    )


# --- старт без дублёра ------------------------------------------------------------


def test_understudy_missing_at_startup_names_the_reason() -> None:
    text = understudy_missing_text("модели qwen3:8b нет на http://127.0.0.1:11434", "Вова")
    assert text == (
        "Вова, я стартовал без дублёра: в конфигурации он включён, но модели qwen3:8b нет "
        "на http://127.0.0.1:11434. Если облако откажет, подстраховать будет некому. "
        "Работаю без дублёра до перезапуска: даже если модель появится, сам я его не "
        "подхвачу."
    )


def test_understudy_missing_without_a_name() -> None:
    assert understudy_missing_text("x", None).startswith("Я стартовал без дублёра")
