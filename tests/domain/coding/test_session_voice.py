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

from bob.coding import session_voice


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


def test_failed_message_reads_as_human_operator_reaction() -> None:
    # BOB-087.B2: on a break Bob REACTS like himself («чёрт, сломалось»), not a dry
    # "STATUS: FAILED" — the operator's human voice, still carrying the detail.
    message = session_voice.failed("boom")
    assert "boom" in message
    assert "чёрт" in message.casefold()


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


def test_gate_reactions_are_human_not_dry_status_labels() -> None:
    # BOB-087.B2: the operator's gate lines read as human reactions in Bob's voice,
    # never machine status labels ("STATUS: DONE") — north star: personality, not a log.
    for message in (
        session_voice.accepted(),
        session_voice.pr("https://x/pr/1"),
        session_voice.failed("d"),
        session_voice.stopped(),
    ):
        lowered = message.casefold()
        assert "status:" not in lowered
        assert "status :" not in lowered


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


# --- resume flow (BOB-087.D3): Bob asks, then reports ---------------------------


def test_resume_confirm_names_the_workspace_and_when_and_asks() -> None:
    line = session_voice.resume_confirm(workspace="epic-bob-087", when="1 августа, 12:00")
    # The owner must see WHICH workspace and WHEN that session was before saying «да».
    assert "epic-bob-087" in line
    assert "1 августа, 12:00" in line
    # 🔴 It is a QUESTION, not an announcement — nothing is raised until the owner agrees.
    assert "?" in line


def test_resume_nothing_names_the_workspace_and_is_honest() -> None:
    line = session_voice.resume_nothing("epic-bob-087")
    assert "epic-bob-087" in line
    assert line.strip()


def test_resume_cancelled_is_short_and_non_empty() -> None:
    assert session_voice.resume_cancelled().strip()


def test_resumed_names_the_workspace() -> None:
    line = session_voice.resumed("epic-bob-087")
    assert "epic-bob-087" in line


def test_resume_failed_is_honest_and_never_promises_cleanup() -> None:
    # 🔴 The persistent workspace is NOT torn down on a failed resume — the accumulated
    # work stays, so the line must not claim Bob removed the working copy.
    line = session_voice.resume_failed()
    assert line.strip()
    assert "убрал" not in line.casefold()


def test_stopped_persistent_never_claims_the_work_was_cleaned_up() -> None:
    # 🔴 BOB-087.D4b: остановка ВОЗОБНОВЛЁННОЙ сессии сохраняет накопленное дерево, поэтому
    # реплика НЕ смеет говорить, что Боб убрал рабочую копию — это была бы ложь owner'у.
    line = session_voice.stopped_persistent()
    assert line.strip()
    assert "убрал" not in line.casefold()


def test_stopped_persistent_says_the_work_survived_and_can_be_raised_again() -> None:
    # Owner должен из одной реплики понять: сеанс погашен, но работа на месте и её можно
    # поднять снова — иначе честность вырождается в умолчание.
    lowered = session_voice.stopped_persistent().casefold()
    assert "остал" in lowered
    assert "подним" in lowered or "поднять" in lowered


def test_stopped_persistent_differs_from_the_ephemeral_stop() -> None:
    # Две разные судьбы дерева — две разные реплики (эфемерная копия действительно убрана).
    assert session_voice.stopped_persistent() != session_voice.stopped()


def test_resume_lines_are_human_not_dry_status_labels() -> None:
    for message in (
        session_voice.resume_confirm(workspace="w", when="вчера"),
        session_voice.resume_nothing("w"),
        session_voice.resume_cancelled(),
        session_voice.resumed("w"),
        session_voice.resume_failed(),
        session_voice.stopped_persistent(),
    ):
        assert isinstance(message, str)
        assert message.strip()
        assert "status:" not in message.casefold()


# --- сеанс кончился САМ (bob-kv4): смерть процесса — не owner-«стоп» ------------


def test_interactive_ended_never_passes_the_death_off_as_the_owners_stop() -> None:
    # 🔴 bob-kv4: процесс умер САМ — приписывать это команде owner'а нельзя (чужое
    # действие за его). Реплика обязана отличаться от прощания на явный «стоп».
    assert session_voice.interactive_ended() != session_voice.stopped()
    assert session_voice.interactive_ended_persistent() != session_voice.stopped_persistent()


def test_interactive_ended_says_the_session_closed_by_itself() -> None:
    # Owner должен понять из одной реплики: сеанс закрылся не по его команде.
    lowered = session_voice.interactive_ended().casefold()
    assert "сам" in lowered
    assert "GUPPI" in session_voice.interactive_ended()


def test_interactive_ended_reports_the_ephemeral_copy_was_cleaned_up() -> None:
    # Эфемерное дерево действительно убрано — об этом честно сказано (как в ``stopped``).
    assert "убрал" in session_voice.interactive_ended().casefold()


def test_interactive_ended_persistent_never_claims_cleanup_and_invites_to_resume() -> None:
    # 🔴 Долгоживущий workspace НЕ убирается — реплика про уборку молчит и зовёт поднять.
    lowered = session_voice.interactive_ended_persistent().casefold()
    assert "убрал" not in lowered
    assert "остал" in lowered
    assert "подним" in lowered or "поднять" in lowered


def test_interactive_ended_lines_are_human_not_dry_status_labels() -> None:
    for message in (
        session_voice.interactive_ended(),
        session_voice.interactive_ended_persistent(),
    ):
        assert isinstance(message, str)
        assert message.strip()
        assert "status:" not in message.casefold()
