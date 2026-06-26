# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты session_voice — голос Боба на гейтах coding-сессии (BOB-041 .3).

Канон Бобиверса: Боб — личность, дирижирует от первого лица; GUPPI — сухой
исполнитель, которым Боб правит. Эти билдеры — чистые детерминированные шаблоны
(никакого LLM): реплики берусь / план готов / готово-PR / провал / нет-правок /
остановил — в персоне Боба, с GUPPI как исполнителем. Тесты пинят присутствие
маркеров (первое лицо, упоминание GUPPI, встроенный план, render-safe), не точную
формулировку.
"""

from __future__ import annotations

from bob.domain.coding import session_voice


def test_accepted_is_bob_first_person_directing_guppi() -> None:
    line = session_voice.accepted()
    assert line
    assert "GUPPI" in line
    # Bob speaks in the first person when he takes the task on.
    assert "берусь" in line.casefold()


def test_plan_message_embeds_the_cleaned_plan_and_frames_guppi() -> None:
    plan = "## План\n1. Правка файла\n2. Тесты"
    message = session_voice.plan(plan)
    # The (already cleaned) plan body is embedded verbatim for the rich/markdown path.
    assert plan in message
    # Bob presents it; GUPPI drafted the detail.
    assert "GUPPI" in message
    # An approval hint is present so the owner knows how to proceed.
    assert "давай" in message.casefold() or "approve" in message.casefold()


def test_plan_message_without_plan_falls_back_to_no_plan_note() -> None:
    message = session_voice.plan("")
    assert message
    assert "GUPPI" in message or "план" in message.casefold()


def test_pr_message_is_bob_voiced_done_with_url_and_never_merge() -> None:
    url = "https://github.com/x/bob/pull/7"
    message = session_voice.pr(url)
    assert url in message
    assert "GUPPI" in message
    # Bob frames it as done; never-merge-main reminder stays.
    assert "готов" in message.casefold()
    assert "main" in message.casefold()


def test_no_changes_message_is_honest_and_mentions_no_edits() -> None:
    message = session_voice.no_changes()
    assert message
    # Existing assistant test pins on «не внёс» / «изменени».
    assert "не внёс" in message or "изменени" in message.casefold()


def test_failed_message_carries_the_detail() -> None:
    message = session_voice.failed("claude timed out")
    assert "claude timed out" in message


def test_stopped_message_is_bob_voiced_and_non_empty() -> None:
    message = session_voice.stopped()
    assert message
    assert "GUPPI" in message or "останов" in message.casefold()


def test_busy_cannot_approve_no_session_are_non_empty() -> None:
    assert session_voice.busy()
    assert session_voice.cannot_approve()
    assert session_voice.no_session()


def test_status_line_carries_task_state_branch() -> None:
    line = session_voice.status_line(task="Починить парсер", state="plan_ready", branch="bob/fix")
    assert "Починить парсер" in line
    assert "plan_ready" in line
    assert "bob/fix" in line


def test_status_idle_is_non_empty() -> None:
    assert session_voice.status_idle()


def test_all_messages_are_render_safe_single_strings() -> None:
    # No builder returns None / empty for its happy path — every one is a real string.
    for message in (
        session_voice.accepted(),
        session_voice.plan("p"),
        session_voice.pr("u"),
        session_voice.no_changes(),
        session_voice.failed("d"),
        session_voice.stopped(),
    ):
        assert isinstance(message, str)
        assert message.strip()
