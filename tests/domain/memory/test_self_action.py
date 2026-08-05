# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure self-action domain core (no I/O) — BOB-079.1.

``describe_self_action`` is the mutation core: a deterministic FIRST-PERSON
Russian renderer. Every content string opens with «я …» (INV-1); anomalies
(failure/runaway) are flagged and carry the ``anomaly`` tag (INV honesty).
"""

from __future__ import annotations

import pytest

from bob.memory.self_action import (
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
