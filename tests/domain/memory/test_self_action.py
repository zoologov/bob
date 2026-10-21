# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure self-action domain core (no I/O) — BOB-079.1.

``describe_self_action`` is the mutation core: a deterministic FIRST-PERSON
Russian renderer. Every content string opens with «я …» (INV-1); anomalies
(failure/runaway) are flagged and carry the ``anomaly`` tag (INV honesty).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from bob.memory.self_action import (
    OutageSpan,
    RenderedSelfAction,
    SelfAction,
    SelfActionKind,
    coding_terminal_kind,
    describe_self_action,
)

_ANOMALY_KINDS = {
    SelfActionKind.CODING_FAILED,
    SelfActionKind.CODING_RUNAWAY,
    SelfActionKind.TOOL_FAILURE,
}


@pytest.mark.parametrize("kind", list(SelfActionKind))
def test_content_is_always_first_person(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind, target="X"))
    assert rendered.content.startswith("я ")


@pytest.mark.parametrize("kind", list(SelfActionKind))
def test_content_first_person_without_target(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind))
    assert rendered.content.startswith("я ")
    # A missing target must not leave dangling empty quotes.
    assert "«»" not in rendered.content


@pytest.mark.parametrize("kind", list(SelfActionKind))
def test_self_tag_always_present(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind, target="X"))
    assert "self" in rendered.tags


@pytest.mark.parametrize("kind", list(SelfActionKind))
def test_anomaly_flag_matches_kind(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind, target="X"))
    assert rendered.is_anomaly is (kind in _ANOMALY_KINDS)


@pytest.mark.parametrize("kind", sorted(_ANOMALY_KINDS))
def test_anomaly_kinds_carry_anomaly_tag(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind, target="X"))
    assert "anomaly" in rendered.tags


@pytest.mark.parametrize("kind", [k for k in SelfActionKind if k not in _ANOMALY_KINDS])
def test_non_anomaly_kinds_omit_anomaly_tag(kind: SelfActionKind) -> None:
    rendered = describe_self_action(SelfAction(kind=kind, target="X"))
    assert "anomaly" not in rendered.tags


def test_coding_started_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_STARTED, target="BOB-079")
    )
    assert rendered == RenderedSelfAction(
        content="я взялся за «BOB-079» в кодере",
        tags=("self", "coding"),
        is_anomaly=False,
    )


def test_coding_started_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_STARTED))
    assert rendered.content == "я взялся за работу в кодере"


def test_coding_finished_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_FINISHED, target="BOB-079")
    )
    assert rendered.content == "я доделал «BOB-079», открыл PR"
    assert rendered.tags == ("self", "coding")


# --- Финал сессии: Боб присваивает себе ровно то, что сделал (BOB-089, bob-a6b.8) ----
# Форк-путь: PR открывает owner по ссылке, поэтому «открыл PR» было бы ложным
# самовоспоминанием — тем самым, из которого потом растёт конфабуляция с провенансом
# «я сам так сделал».


def test_coding_handed_off_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_HANDED_OFF, target="BOB-089")
    )
    assert rendered.content == (
        "я довёл «BOB-089» до ветки в своём форке и отдал ссылку — PR не открывал"
    )
    assert rendered.tags == ("self", "coding")
    assert rendered.is_anomaly is False


def test_coding_handed_off_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_HANDED_OFF))
    assert rendered.content == (
        "я довёл работу до ветки в своём форке и отдал ссылку — PR не открывал"
    )


@pytest.mark.parametrize("target", ["BOB-089", None])
def test_handed_off_never_claims_an_opened_pr(target: str | None) -> None:
    # 🔴 Не косметика: этот эпизод — источник будущих ответов Боба о себе. Заявление о
    # совершённом действии здесь = конфабуляция «я это помню, я сам так сделал».
    content = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_HANDED_OFF, target=target)
    ).content
    assert "открыл PR" not in content
    assert "PR открыт" not in content


def test_finished_kind_still_claims_the_pr_it_really_opened() -> None:
    # Парность: на gh-пути PR действительно открывает Боб, и присвоить его он ОБЯЗАН.
    content = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_FINISHED, target="BOB-089")
    ).content
    assert "открыл PR" in content


def test_terminal_kind_follows_whether_a_pr_was_really_opened() -> None:
    assert coding_terminal_kind(opened_pr=True) is SelfActionKind.CODING_FINISHED
    assert coding_terminal_kind(opened_pr=False) is SelfActionKind.CODING_HANDED_OFF


def test_coding_aborted_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_ABORTED, target="BOB-079")
    )
    assert rendered.content == "я прервал сессию по «BOB-079» — меня остановили"


def test_coding_failed_with_detail() -> None:
    rendered = describe_self_action(
        SelfAction(
            kind=SelfActionKind.CODING_FAILED, target="BOB-079", detail="таймаут"
        )
    )
    assert rendered.content == "я не справился с «BOB-079» — сессия упала: таймаут"
    assert rendered.is_anomaly is True
    assert rendered.tags == ("self", "coding", "anomaly")


def test_coding_failed_without_detail() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_FAILED, target="BOB-079")
    )
    assert rendered.content == "я не справился с «BOB-079» — сессия упала"


def test_coding_runaway_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_RUNAWAY, target="BOB-079")
    )
    assert (
        rendered.content
        == "я залип на «BOB-079» — флудил правками, пришлось себя осадить"
    )
    assert rendered.is_anomaly is True
    assert rendered.tags == ("self", "coding", "anomaly")


def test_tool_use_with_target() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.TOOL_USE, target="read_code, list_dir")
    )
    assert rendered.content == "я воспользовался инструментами: read_code, list_dir"
    assert rendered.tags == ("self", "tools")
    assert rendered.is_anomaly is False


def test_tool_failure_with_detail() -> None:
    rendered = describe_self_action(
        SelfAction(
            kind=SelfActionKind.TOOL_FAILURE, target="read_code", detail="нет файла"
        )
    )
    assert rendered.content == "я попробовал read_code — не вышло: нет файла"
    assert rendered.is_anomaly is True
    assert rendered.tags == ("self", "tools", "anomaly")


def test_tool_failure_without_detail() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.TOOL_FAILURE, target="read_code")
    )
    assert rendered.content == "я попробовал read_code — не вышло"


# --- Exact no-target phrasing for EVERY branch (mutation hardening) ------------
# Each ``if target ... else`` arm hides a distinct RU literal; without an exact
# assertion on the ELSE arm a mutmut mutation of that literal survives. These pin
# the graceful target=None phrasing of every kind whose else-arm wasn't yet fixed.


def test_coding_finished_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_FINISHED))
    assert rendered.content == "я доделал работу, открыл PR"


def test_coding_aborted_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_ABORTED))
    assert rendered.content == "я прервал сессию — меня остановили"


def test_coding_failed_without_target_without_detail() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_FAILED))
    assert rendered.content == "я не справился — сессия упала"


def test_coding_failed_without_target_with_detail() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_FAILED, detail="таймаут")
    )
    assert rendered.content == "я не справился — сессия упала: таймаут"


def test_coding_runaway_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.CODING_RUNAWAY))
    assert rendered.content == "я залип — флудил правками, пришлось себя осадить"
    assert rendered.is_anomaly is True


def test_tool_use_without_target() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.TOOL_USE))
    assert rendered.content == "я воспользовался инструментами"


def test_tool_failure_without_target_without_detail() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.TOOL_FAILURE))
    assert rendered.content == "я попробовал воспользоваться инструментом — не вышло"


def test_tool_failure_without_target_with_detail() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.TOOL_FAILURE, detail="нет сети")
    )
    assert rendered.content == "я попробовал воспользоваться инструментом — не вышло: нет сети"


# --- Empty-string detail is treated as "no reason" (falsy) — boundary ---------
# ``_detail_suffix`` guards on ``if detail``; an empty string must add NO suffix.
# This pins the falsy boundary so a mutant flipping the guard to ``is not None``
# (which would append ": ") is killed.


def test_coding_failed_empty_detail_adds_no_suffix() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.CODING_FAILED, target="X", detail="")
    )
    assert rendered.content == "я не справился с «X» — сессия упала"


def test_tool_failure_empty_detail_adds_no_suffix() -> None:
    rendered = describe_self_action(
        SelfAction(kind=SelfActionKind.TOOL_FAILURE, target="read_code", detail="")
    )
    assert rendered.content == "я попробовал read_code — не вышло"


# --- Tool kinds carry the ``tools`` area tag, coding kinds the ``coding`` one --
# ``_tags_for`` picks the area via ``_CODING_KINDS`` membership; pin BOTH literals
# so a mutation of the area constant or the membership test is caught.


def test_tool_kinds_carry_tools_area_tag() -> None:
    for kind in (SelfActionKind.TOOL_USE, SelfActionKind.TOOL_FAILURE):
        tags = describe_self_action(SelfAction(kind=kind, target="x")).tags
        assert "tools" in tags
        assert "coding" not in tags


def test_coding_kinds_carry_coding_area_tag() -> None:
    coding_kinds = [
        SelfActionKind.CODING_STARTED,
        SelfActionKind.CODING_FINISHED,
        SelfActionKind.CODING_HANDED_OFF,
        SelfActionKind.CODING_ABORTED,
        SelfActionKind.CODING_FAILED,
        SelfActionKind.CODING_RUNAWAY,
    ]
    for kind in coding_kinds:
        tags = describe_self_action(SelfAction(kind=kind, target="x")).tags
        assert "coding" in tags
        assert "tools" not in tags


def test_self_tag_leads_the_tag_tuple() -> None:
    # The ``self`` tag is always first — it marks the memory as Bob's OWN deed.
    for kind in SelfActionKind:
        tags = describe_self_action(SelfAction(kind=kind, target="x")).tags
        assert tags[0] == "self"


# --- Простой провайдера: Боб помнит, что молчал и почему (BOB-116 D7, bob-i83.3) ------
# Эпизод пишется на переходе RECOVERED: Боб присваивает себе ровно то, что было, —
# он молчал, потому что думать было нечем, и называет причину человеческими словами, а
# не кодом HTTP. Время рендерится так, как его несёт datetime (пояс выбирает адаптер).

_MSK = timezone(timedelta(hours=3))


def _outage(
    *,
    since: datetime = datetime(2026, 10, 1, 6, 10, tzinfo=_MSK),
    until: datetime = datetime(2026, 10, 10, 5, 42, tzinfo=_MSK),
    failure_class: str | None = "auth",
    provider: str = "tier0-primary",
) -> SelfAction:
    return SelfAction(
        kind=SelfActionKind.OUTAGE_RECOVERED,
        outage=OutageSpan(
            since=since, until=until, failure_class=failure_class, provider=provider
        ),
    )


def test_outage_recovered_full_first_person_story() -> None:
    rendered = describe_self_action(_outage())
    assert rendered == RenderedSelfAction(
        content=(
            "я молчал с 1 октября 06:10 по 10 октября 05:42 +03:00 (8 дней 23 часа): "
            "облако не пускало меня по ключу/квоте, думать было нечем. Теперь снова могу."
        ),
        tags=("self", "outage"),
        is_anomaly=False,
    )


@pytest.mark.parametrize(
    ("failure_class", "phrase"),
    [
        ("auth", "облако не пускало меня по ключу/квоте"),
        ("rate", "облако просило меня подождать"),
        ("server", "облако падало на своей стороне"),
        ("timeout", "облако не отвечало"),
        ("connection", "до облака было не достучаться"),
        ("shape", "облако обрывало ответ на полуслове"),
        ("contract", "облако отвергало мой запрос"),
        (None, "облако не работало"),
        ("teapot", "облако не работало (teapot)"),
    ],
)
def test_outage_cause_is_told_in_human_words(failure_class: str | None, phrase: str) -> None:
    content = describe_self_action(_outage(failure_class=failure_class)).content
    assert content == (
        "я молчал с 1 октября 06:10 по 10 октября 05:42 +03:00 (8 дней 23 часа): "
        f"{phrase}, думать было нечем. Теперь снова могу."
    )


@pytest.mark.parametrize(
    ("failure_class", "phrase"),
    [
        ("auth", "дублёр не пускал меня по ключу/квоте"),
        ("rate", "дублёр просил меня подождать"),
        ("server", "дублёр падал на своей стороне"),
        ("timeout", "дублёр не отвечал"),
        ("connection", "до дублёра было не достучаться"),
        ("shape", "дублёр обрывал ответ на полуслове"),
        ("contract", "дублёр отвергал мой запрос"),
        (None, "дублёр не работал"),
    ],
)
def test_outage_of_the_local_understudy_is_not_blamed_on_the_cloud(
    failure_class: str | None, phrase: str
) -> None:
    # Дублёр живёт на машине Боба: назвать его «облаком» — ложное воспоминание о себе.
    content = describe_self_action(
        _outage(failure_class=failure_class, provider="tier0-understudy")
    ).content
    assert f": {phrase}, думать было нечем." in content
    assert "облак" not in content


# Говорящий — тот же, что в сообщении владельцу о том же простое (ревью M3, bob-i83.20):
# владельцу Tier-1 — «основная модель», и память Боба называет его так же, а не «облаком».
@pytest.mark.parametrize(
    ("provider", "phrase"),
    [
        ("tier0-primary", ": облако не пускало меня по ключу/квоте,"),
        ("tier1", ": основная модель не пускала меня по ключу/квоте,"),
        ("tier9", ": провайдер tier9 не пускал меня по ключу/квоте,"),
    ],
)
def test_provider_is_named_as_in_the_owner_message(provider: str, phrase: str) -> None:
    content = describe_self_action(_outage(provider=provider)).content
    assert phrase in content


@pytest.mark.parametrize(
    "failure_class", ["auth", "rate", "server", "timeout", "connection", "shape", "contract"]
)
def test_outage_story_carries_no_http_jargon(failure_class: str) -> None:
    content = describe_self_action(_outage(failure_class=failure_class)).content
    for jargon in ("401", "403", "429", "4xx", "5xx", "HTTP", failure_class):
        assert jargon not in content


def test_outage_within_one_day_names_the_day_once() -> None:
    content = describe_self_action(
        _outage(
            since=datetime(2026, 10, 1, 6, 10, tzinfo=_MSK),
            until=datetime(2026, 10, 1, 6, 42, tzinfo=_MSK),
        )
    ).content
    assert content.startswith("я молчал 1 октября с 06:10 по 06:42 +03:00 (32 минуты): ")


def test_outage_across_new_year_names_both_years() -> None:
    content = describe_self_action(
        _outage(
            since=datetime(2026, 12, 31, 23, 50, tzinfo=_MSK),
            until=datetime(2027, 1, 1, 0, 5, tzinfo=_MSK),
        )
    ).content
    assert content.startswith(
        "я молчал с 31 декабря 2026 23:50 по 1 января 2027 00:05 +03:00 (15 минут): "
    )


# Пояс эпизода — тот, в котором его несёт datetime (переводит адаптер сборки), и он назван
# смещением — как в сообщении владельцу и в /status (bob-i83.15). Два пояса, ни один не
# совпадает с другим: рендер, который подписал бы чужой пояс или «UTC», краснеет на любой машине.
@pytest.mark.parametrize(
    ("tz", "period"),
    [
        (timezone(timedelta(hours=5, minutes=45)), "1 октября с 06:10 по 06:42 +05:45"),
        (timezone(-timedelta(hours=9, minutes=30)), "1 октября с 06:10 по 06:42 -09:30"),
    ],
)
def test_outage_period_names_the_offset_of_its_zone(tz: tzinfo, period: str) -> None:
    content = describe_self_action(
        _outage(
            since=datetime(2026, 10, 1, 6, 10, tzinfo=tz),
            until=datetime(2026, 10, 1, 6, 42, tzinfo=tz),
        )
    ).content
    assert content.startswith(f"я молчал {period} (32 минуты): ")
    assert "UTC" not in content


def test_outage_with_naive_times_carries_no_offset() -> None:
    content = describe_self_action(
        _outage(
            since=datetime(2026, 10, 1, 6, 10),  # noqa: DTZ001 - наивное время — предмет теста
            until=datetime(2026, 10, 1, 6, 42),  # noqa: DTZ001
        )
    ).content
    assert content.startswith("я молчал 1 октября с 06:10 по 06:42 (32 минуты): ")


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
def test_outage_month_is_in_russian_genitive(month: int, genitive: str) -> None:
    content = describe_self_action(
        _outage(
            since=datetime(2026, month, 2, 9, 5, tzinfo=_MSK),
            until=datetime(2026, month, 3, 9, 5, tzinfo=_MSK),
        )
    ).content
    assert content.startswith(f"я молчал со 2 {genitive} 09:05 по 3 {genitive} 09:05 +03:00 (")


# Длительность — та же, что в сообщении владельцу («Молчал 2 часа 15 минут»), из
# bob.kernel.ru_text: винительный падеж, единица с числом 1 — без числа (ревью M3,
# bob-i83.20). Полная таблица форм — в tests/domain/kernel/test_ru_text.py.
@pytest.mark.parametrize(
    ("seconds", "duration"),
    [
        (0, "меньше секунды"),
        (59, "59 секунд"),
        (60, "минуту"),
        (119, "минуту"),
        (120, "2 минуты"),
        (4 * 60, "4 минуты"),
        (5 * 60, "5 минут"),
        (11 * 60, "11 минут"),
        (12 * 60, "12 минут"),
        (14 * 60, "14 минут"),
        (21 * 60, "21 минуту"),
        (22 * 60, "22 минуты"),
        (25 * 60, "25 минут"),
        (3600, "час"),
        (3600 + 60, "1 час 1 минуту"),
        (2 * 3600 + 5 * 60, "2 часа 5 минут"),
        (5 * 3600, "5 часов"),
        (11 * 3600, "11 часов"),
        (21 * 3600, "21 час"),
        (23 * 3600 + 59 * 60, "23 часа 59 минут"),
        (86400, "день"),
        (86400 + 3600, "1 день 1 час"),
        (86400 + 5 * 60, "день"),
        (2 * 86400 + 4 * 3600, "2 дня 4 часа"),
        (5 * 86400, "5 дней"),
        (11 * 86400, "11 дней"),
        (21 * 86400, "21 день"),
        (22 * 86400, "22 дня"),
        (111 * 86400, "111 дней"),
        (112 * 86400, "112 дней"),
    ],
)
def test_outage_duration_reads_as_russian(seconds: int, duration: str) -> None:
    since = datetime(2026, 1, 1, 0, 0, tzinfo=_MSK)
    content = describe_self_action(
        _outage(since=since, until=since + timedelta(seconds=seconds))
    ).content
    assert f" ({duration}): " in content


def test_outage_story_degrades_without_a_span() -> None:
    rendered = describe_self_action(SelfAction(kind=SelfActionKind.OUTAGE_RECOVERED))
    assert rendered.content == "я молчал — думать было нечем. Теперь снова могу."
    assert rendered.tags == ("self", "outage")
    assert rendered.is_anomaly is False


def test_outage_story_ignores_a_target() -> None:
    # У простоя нет «задачи»: target не должен просочиться в воспоминание.
    content = describe_self_action(
        SelfAction(kind=SelfActionKind.OUTAGE_RECOVERED, target="X")
    ).content
    assert content == "я молчал — думать было нечем. Теперь снова могу."


def test_outage_span_refuses_an_end_before_its_start() -> None:
    since = datetime(2026, 10, 10, 6, 42, tzinfo=_MSK)
    with pytest.raises(ValueError, match="until"):
        OutageSpan(
            since=since,
            until=since - timedelta(seconds=1),
            failure_class="auth",
            provider="tier0-primary",
        )


def test_outage_span_carries_its_facts() -> None:
    since = datetime(2026, 10, 1, 6, 10, tzinfo=_MSK)
    until = datetime(2026, 10, 10, 6, 42, tzinfo=_MSK)
    action = _outage(since=since, until=until, failure_class="rate", provider="tier1")
    assert action.outage == OutageSpan(
        since=since, until=until, failure_class="rate", provider="tier1"
    )
    assert action.detail is None
