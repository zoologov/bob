# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Первый кадр конвейера — чистое ядро постановки задачи (BOB-088, срез 2).

Предмет: :func:`bob.interactive.pipeline_prompt.pipeline_first_frame` — ТЕКСТ, которым живая
сессия начинается. Он определяет поведение конвейера (пойдёт ли работа по процессу или
claude начнёт импровизировать), поэтому живёт в домене и является mutation-целью, а не
строкой в адаптере (§0.3 п.7).

Два уровня утверждений, и оба нужны:

* СМЫСЛОВЫЕ — на каждый элемент, ради которого кадр вообще существует (задача дословно,
  указание на ``CLAUDE.md``, ``/coordinator`` для эпика, роли субагентами, трекер ``bd``).
  Они объясняют, ЗАЧЕМ в кадре каждая строка;
* ДОСЛОВНЫЙ (golden) — кадр целиком. 🔴 Это сознательный change-detector: текст промпта
  ЕСТЬ контракт с моделью, и менять его можно только осознанно, вместе с этим тестом.
  Он же делает mutation-гейт настоящим: подстрочная проверка мутанта ``"XX…XX"`` НЕ
  убивает (обёртка встаёт по краям литерала, середина цела), а равенство — убивает.
"""

from __future__ import annotations

import pytest

from bob.interactive.pipeline_prompt import (
    permission_retry_frame,
    pipeline_first_frame,
)

_TASK = "BOB-088: довести конвейер до PR"


def _frame(task: str = _TASK) -> str:
    frame = pipeline_first_frame(task)
    assert frame is not None
    return frame


# --------------------------------------------------------------------------- #
# Смысл: зачем в кадре каждая строка
# --------------------------------------------------------------------------- #


def test_the_frame_carries_the_owners_task_verbatim() -> None:
    assert _TASK in _frame()


def test_the_frame_points_at_the_process_entry_point() -> None:
    # Без этого claude пойдёт «делать задачу», а не вести её по процессу.
    assert "CLAUDE.md" in _frame()


def test_an_epic_is_told_to_go_through_the_coordinator() -> None:
    assert "/coordinator" in _frame()


def test_the_roles_are_told_to_run_as_subagents() -> None:
    frame = _frame()
    assert "СУБАГЕНТАМИ" in frame
    for role in ("dev", "test", "review", "tech-writer"):
        assert role in frame


def test_a_single_bead_is_told_to_take_the_role_inline() -> None:
    assert ".claude/agents/" in _frame()


def test_the_frame_says_the_tracker_is_reachable_from_here() -> None:
    # 🔴 Половина среза 2 — провизионирование клона под ``bd``; кадр обязан сказать, что
    # трекер доступен, иначе модель, однажды упёршись в «no beads database found», решит
    # вести работу без беад.
    assert "bd" in _frame()


def test_the_frame_starts_the_turn_instead_of_waiting_for_one() -> None:
    # Живая проба (RFC): первый кадр в открытый stdin ЗАПУСКАЕТ ход. Кадр обязан читаться
    # как постановка, а не как приветствие, иначе сессия молча ждёт owner'а.
    assert "начинай" in _frame().casefold()


# --------------------------------------------------------------------------- #
# Форма: задача дословно, включая многострочную
# --------------------------------------------------------------------------- #


def test_the_task_keeps_its_own_line_breaks() -> None:
    task = "Первая строка\nвторая строка"
    assert task in _frame(task)


def test_the_surrounding_whitespace_of_the_task_is_trimmed() -> None:
    assert _frame("  задача  ") == _frame("задача")


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_task_yields_no_frame_at_all(blank: str) -> None:
    # 🔴 Пустая постановка ХУЖЕ отсутствующей: «Задача от owner'а:» без задачи модель
    # додумает сама и начнёт делать выдуманную работу конвейером. Кадра нет — сессия
    # открыта и просто ждёт owner'а, ровно как до среза.
    assert pipeline_first_frame(blank) is None


# --------------------------------------------------------------------------- #
# 🔴 Дословный контракт кадра
# --------------------------------------------------------------------------- #


def test_the_frame_reads_exactly_like_this() -> None:
    assert pipeline_first_frame(_TASK) == (
        f"Задача от owner'а: {_TASK}\n"
        "\n"
        "Веди её по CLAUDE.md в корне этого рабочего дерева: это входная точка процесса, "
        "прочти её первой.\n"
        "Эпик или иначе многобеадная работа — через /coordinator, роли (dev / test / "
        "review / tech-writer) запускай СУБАГЕНТАМИ.\n"
        "Одна маленькая беада — возьми роль inline по .claude/agents/<роль>.md.\n"
        "Трекер bd доступен из этого рабочего места: беаду возьми или заведи и веди её "
        "состояние там, а не в голове.\n"
        "Это постановка, а не разминка: начинай сам, отдельной команды не будет."
    )


# --------------------------------------------------------------------------- #
# Кадр возвращения после разрешения владельца (BOB-088, срез 3)
# --------------------------------------------------------------------------- #
#
# 🔴 Тесты этого кадра стоят ЗДЕСЬ, в доменных, а не только в тестах менеджера, и это не
# дублирование: mutation-гейт считает покрытие по ``tests/domain`` (конфиг mutmut), и
# кадр, проверенный только выше по стеку, дал бы «no tests» — то есть объявленную
# mutation-цель БЕЗ гейта (§0.3 п.7).


def _retry(command: str = "git push origin bob/x") -> str:
    frame = permission_retry_frame(command)
    assert frame is not None
    return frame


def test_the_retry_frame_names_the_command_the_owner_approved() -> None:
    # Без дословной команды поднятая нить не знает, что именно повторять: расплывчатое
    # «продолжай» модель истолкует как угодно (замерено живым прогоном — см. беаду).
    assert "git push origin bob/x" in _retry()


def test_the_retry_frame_says_the_permission_was_for_one_time() -> None:
    # 🔴 Модель, прочитавшая «тебе разрешили push», может решить, что теперь можно
    # всегда. Одноразовость держится не только argv, но и словами.
    assert "разовое" in _retry()


def test_a_retry_of_nothing_is_no_frame_at_all() -> None:
    assert permission_retry_frame("") is None
    assert permission_retry_frame("   \n") is None


def test_the_retry_frame_is_worded_exactly_like_this() -> None:
    # Дословный контракт с моделью — как и у первого кадра (см. верх файла).
    assert _retry() == (
        "Owner разрешил вот это, словами в личке: git push origin bob/x\n"
        "\n"
        "Повтори ровно эту команду с того места, где упёрся в запрет, и продолжай "
        "работу дальше по процессу.\n"
        "Разрешение разовое: следующий такой шаг снова упрётся в запрет, и я снова "
        "пойду спрашивать."
    )
