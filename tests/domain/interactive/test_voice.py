# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты voice — голос Боба в живом интерактивном сеансе (BOB-083 .3 / BOB-087.D3).

Те же правила, что у голоса гейтед-кодера: чистые детерминированные шаблоны в персоне
Боба, GUPPI как исполнитель, никакого LLM. Тесты пинят присутствие маркеров (что реплика
называет workspace, спрашивает, не врёт про уборку сохранённого дерева и не выдаёт смерть
процесса за owner-«стоп»), а не точную формулировку.

🔴 BOB-087.E (bob-6u2): реплики уехали из :mod:`bob.coding.session_voice` в голос своего
bounded context (:mod:`bob.interactive.voice`) — тесты переехали вместе с ними БЕЗ
изменения ожиданий.
"""

from __future__ import annotations

from bob.interactive import voice

# --- resume flow (BOB-087.D3): Bob asks, then reports ---------------------------


def test_resume_confirm_names_the_workspace_and_when_and_asks() -> None:
    line = voice.resume_confirm(workspace="epic-bob-087", when="1 августа, 12:00")
    # The owner must see WHICH workspace and WHEN that session was before saying «да».
    assert "epic-bob-087" in line
    assert "1 августа, 12:00" in line
    # 🔴 It is a QUESTION, not an announcement — nothing is raised until the owner agrees.
    assert "?" in line


def test_resume_nothing_names_the_workspace_and_is_honest() -> None:
    line = voice.resume_nothing("epic-bob-087")
    assert "epic-bob-087" in line
    assert line.strip()


def test_resume_cancelled_is_short_and_non_empty() -> None:
    assert voice.resume_cancelled().strip()


def test_resumed_names_the_workspace() -> None:
    line = voice.resumed("epic-bob-087")
    assert "epic-bob-087" in line


def test_resume_failed_is_honest_and_never_promises_cleanup() -> None:
    # 🔴 The persistent workspace is NOT torn down on a failed resume — the accumulated
    # work stays, so the line must not claim Bob removed the working copy.
    line = voice.resume_failed()
    assert line.strip()
    assert "убрал" not in line.casefold()


def test_stopped_persistent_never_claims_the_work_was_cleaned_up() -> None:
    # 🔴 BOB-087.D4b: остановка ВОЗОБНОВЛЁННОЙ сессии сохраняет накопленное дерево, поэтому
    # реплика НЕ смеет говорить, что Боб убрал рабочую копию — это была бы ложь owner'у.
    line = voice.stopped_persistent()
    assert line.strip()
    assert "убрал" not in line.casefold()


def test_stopped_persistent_says_the_work_survived_and_can_be_raised_again() -> None:
    # Owner должен из одной реплики понять: сеанс погашен, но работа на месте и её можно
    # поднять снова — иначе честность вырождается в умолчание.
    lowered = voice.stopped_persistent().casefold()
    assert "остал" in lowered
    assert "подним" in lowered or "поднять" in lowered


def test_stopped_persistent_differs_from_the_ephemeral_stop() -> None:
    # Две разные судьбы дерева — две разные реплики (эфемерная копия действительно убрана).
    assert voice.stopped_persistent() != voice.stopped()


def test_resume_lines_are_human_not_dry_status_labels() -> None:
    for message in (
        voice.resume_confirm(workspace="w", when="вчера"),
        voice.resume_nothing("w"),
        voice.resume_cancelled(),
        voice.resumed("w"),
        voice.resume_failed(),
        voice.stopped_persistent(),
    ):
        assert isinstance(message, str)
        assert message.strip()
        assert "status:" not in message.casefold()


# --- сеанс кончился САМ (bob-kv4): смерть процесса — не owner-«стоп» ------------


def test_interactive_ended_never_passes_the_death_off_as_the_owners_stop() -> None:
    # 🔴 bob-kv4: процесс умер САМ — приписывать это команде owner'а нельзя (чужое
    # действие за его). Реплика обязана отличаться от прощания на явный «стоп».
    assert voice.interactive_ended() != voice.stopped()
    assert voice.interactive_ended_persistent() != voice.stopped_persistent()


def test_interactive_ended_says_the_session_closed_by_itself() -> None:
    # Owner должен понять из одной реплики: сеанс закрылся не по его команде.
    lowered = voice.interactive_ended().casefold()
    assert "сам" in lowered
    assert "GUPPI" in voice.interactive_ended()


def test_interactive_ended_reports_the_ephemeral_copy_was_cleaned_up() -> None:
    # Эфемерное дерево действительно убрано — об этом честно сказано (как в ``stopped``).
    assert "убрал" in voice.interactive_ended().casefold()


def test_interactive_ended_persistent_never_claims_cleanup_and_invites_to_resume() -> None:
    # 🔴 Долгоживущий workspace НЕ убирается — реплика про уборку молчит и зовёт поднять.
    lowered = voice.interactive_ended_persistent().casefold()
    assert "убрал" not in lowered
    assert "остал" in lowered
    assert "подним" in lowered or "поднять" in lowered


def test_interactive_ended_lines_are_human_not_dry_status_labels() -> None:
    for message in (
        voice.interactive_ended(),
        voice.interactive_ended_persistent(),
    ):
        assert isinstance(message, str)
        assert message.strip()
        assert "status:" not in message.casefold()
