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
from typing import TYPE_CHECKING

import pytest

from bob.application.router.health_messages import (
    HealthNotice,
    Situation,
    degraded_text,
    recovered_text,
    reminder_text,
    understudy_missing_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SINCE = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)


def _notice(
    *,
    provider_id: str = "tier0-primary",
    situation: Situation = Situation.MUTE,
    failure_class: str | None = "auth",
    failures: int = 5,
    elapsed: timedelta = timedelta(minutes=3),
    has_understudy: bool = False,
    owner_address: str | None = "Вова",
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
        owner_address=owner_address,
    )


# Длительность, период, склонение и причина отказа — общие слова из ``bob.kernel.ru_text``
# (ревью M3, bob-i83.20); их полные таблицы — в tests/domain/kernel/test_ru_text.py. Здесь —
# что эти слова доходят до текста владельцу на своих местах.


# --- сигнал о деградации ----------------------------------------------------------


def test_mute_without_understudy_matches_the_approved_wording() -> None:
    text = degraded_text(_notice())
    assert text == (
        "Вова, я не могу думать: облако отказывает мне в доступе (401/403 — ключ или "
        "квота) уже 3 минуты, 5 запросов подряд. Дублёра на этой машине нет — я помолчу "
        "и буду пробовать раз в минуту, потом реже. Напомню через 10 минут, если не пройдёт."
    )


def test_without_owner_address_the_message_starts_with_a_capital() -> None:
    text = degraded_text(_notice(owner_address=None))
    assert text.startswith("Я не могу думать: облако")


def test_blank_owner_address_is_treated_as_no_address() -> None:
    assert degraded_text(_notice(owner_address="  ")).startswith("Я не могу думать")


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


# Отказ основной модели — это не «говорю слабее»: ход владельца и любого не-гостя идёт через
# инструменты (ToolLoop) без отступления на Tier-0 и кончается уведомлением GUPPI «Боб временно
# недоступен» (S13). Слабее, облаком Tier-0, отвечают только гости — пока оно живо (ревью N2,
# bob-i83.24; путь гостя проверен на собранной программе, S14).
def test_voice_down_matches_the_approved_wording() -> None:
    text = degraded_text(
        _notice(
            provider_id="tier1",
            situation=Situation.VOICE_DOWN,
            elapsed=timedelta(minutes=4),
            failures=6,
            next_reminder_s=3600,
        )
    )
    assert text == (
        "Вова, основная модель отказывает мне в доступе (401/403 — ключ или квота) уже "
        "4 минуты, 6 запросов подряд. Тебе и команде я сейчас ответить не могу — вместо меня "
        "GUPPI пишет, что я недоступен. Гостям отвечаю облаком попроще, пока оно живо. "
        "Основную модель надо чинить. Напомню через час, если не пройдёт."
    )


def test_voice_tier_down_names_the_main_model_and_does_not_promise_a_weaker_voice() -> None:
    text = degraded_text(
        _notice(provider_id="tier1", situation=Situation.VOICE_DOWN, failure_class="rate")
    )
    assert text.startswith("Вова, основная модель просит подождать (429")
    assert "Тебе и команде я сейчас ответить не могу" in text
    assert "в полную силу" not in text


@pytest.mark.parametrize("make", [degraded_text, reminder_text], ids=["degraded", "reminder"])
def test_voice_down_names_the_main_model_once_per_sentence(
    make: Callable[[HealthNotice], str],
) -> None:
    text = make(_notice(provider_id="tier1", situation=Situation.VOICE_DOWN))
    sentences = [sentence for sentence in text.split(". ") if sentence]
    assert all(sentence.lower().count("основн") <= 1 for sentence in sentences), sentences


@pytest.mark.parametrize(
    ("failure_class", "fragment"),
    [
        ("auth", "отказывает мне в доступе (401/403 — ключ или квота)"),
        ("rate", "просит подождать (429 — лимит запросов)"),
        ("server", "отвечает ошибкой сервера (5xx)"),
        ("timeout", "не отвечает вовремя (таймаут)"),
        ("connection", "до облака не достучаться (соединение)"),
        ("shape", "обрывает ответ на полуслове"),
        ("contract", "отвергает мой запрос"),
        (None, "облако не работает"),
        ("unheard-of", "облако не работает (unheard-of)"),
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
        (
            Situation.VOICE_DOWN,
            "tier1",
            "Вова, я всё ещё не могу ответить ни тебе, ни команде: основная модель ",
        ),
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
        _notice(owner_address=None, elapsed=timedelta(days=9, hours=23, minutes=32)), tz=UTC
    )
    assert text == (
        "Я вернулся: облако ответило. Молчал 9 дней 23 часа "
        "(с 1 октября 06:10 по 11 октября 05:42 +00:00)."
    )


def test_recovered_within_one_day_names_the_day_once() -> None:
    text = recovered_text(_notice(elapsed=timedelta(minutes=32)), tz=UTC)
    assert text.endswith("Молчал 32 минуты (1 октября с 06:10 до 06:42 +00:00).")


def test_recovered_period_from_the_second_takes_so() -> None:
    # Тот же предлог, что в эпизоде «я молчал»: «со 2 октября» (ревью M3 — копии расходились).
    since = datetime(2026, 10, 2, 6, 10, tzinfo=UTC)
    notice = HealthNotice(
        provider_id="tier0-primary",
        situation=Situation.MUTE,
        failure_class="auth",
        failures=5,
        since=since,
        now=since + timedelta(days=1),
        next_reminder_s=600.0,
        probe_s=60.0,
        has_understudy=False,
        owner_address=None,
    )
    assert recovered_text(notice, tz=UTC).endswith(
        "Молчал сутки (со 2 октября 06:10 по 3 октября 06:10 +00:00)."
    )


# Время владельцу — в поясе процесса с явным смещением, без «UTC» (решение координатора,
# bob-i83.15). Два пояса, ни один не UTC: реализация, которая игнорирует ``tz`` или печатает
# пояс часов, краснеет на любой машине — с поясом машины совпадёт максимум один случай.
@pytest.mark.parametrize(
    ("tz", "period"),
    [
        (timezone(timedelta(hours=3)), "(1 октября с 09:10 до 09:42 +03:00)"),
        (timezone(-timedelta(hours=9, minutes=30)), "(30 сентября с 20:40 до 21:12 -09:30)"),
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
    assert text.endswith(f"до {local_until:%H:%M} {zone[:3]}:{zone[3:]}).")
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
        owner_address=None,
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
        owner_address=None,
    )
    assert recovered_text(notice, tz=timezone(timedelta(hours=3))).endswith(
        "(1 октября с 06:10 до 06:15)."
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
