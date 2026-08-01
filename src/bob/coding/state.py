# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Машина состояний coding-сессии — чистая, детерминированная (BOB-039 .1).

``CodingSessionState`` — строковый ``Enum`` (значение совпадает с тем, что кладётся
в SQLite TEXT-колонку, так round-trip тривиален). Разрешённые переходы заданы
таблицей; :func:`can_transition` — чистый предикат «можно ли перейти из ``frm`` в
``to``».

🔴 КЛЮЧЕВОЕ (двойной гейт, непробиваемый на уровне домена): ``EXECUTING`` достижимо
ИСКЛЮЧИТЕЛЬНО из ``PLAN_READY`` — это гейт плана. Ни ``PROPOSED``, ни ``PLANNING``,
ни любое иное состояние не ведёт в ``EXECUTING`` (таблица ниже содержит ``EXECUTING``
ровно в одном множестве — целей ``PLAN_READY``). Переход ``PLAN_READY → EXECUTING``
валиден на уровне домена, но его ИНИЦИИРУЕТ только явная owner-команда ``approve_plan``
на уровне use-case (.3). Мержа в машине нет — Боб открывает PR и останавливается:
``PR_OPEN`` — УСПЕШНЫЙ ТЕРМИНАЛ (BOB-042). Открыв PR, Боб закончил свою работу; мерж
делает owner асинхронно на GitHub, вне Боба. Поэтому ``PR_OPEN`` НЕ блокирует новую
сессию (``is_terminal(PR_OPEN)`` — ``True``), и это не создаёт нового пути в
``EXECUTING`` (гейт плана остаётся ровно из ``PLAN_READY``).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CodingSessionState",
    "can_approve_plan",
    "can_start",
    "can_stop",
    "can_transition",
    "is_terminal",
]


class CodingSessionState(StrEnum):
    """Состояние coding-сессии — гейтед жизненный цикл под owner-контролем.

    ``PROPOSED`` (поставлена, ждёт старта) → ``PLANNING`` (Claude Code в plan-mode
    строит план) → ``PLAN_READY`` (план готов, ждёт owner-апрува — ГЕЙТ ПЛАНА) →
    ``EXECUTING`` (план одобрен, идёт исполнение в worktree) → ``PR_OPEN`` — УСПЕШНЫЙ
    ТЕРМИНАЛ (PR открыт, работа Боба завершена; мерж делает owner асинхронно вне Боба,
    BOB-042). ``CANCELLED`` (kill-switch owner'а из любого нетерминального), ``FAILED``
    (честный провал/таймаут) и легаси-``DONE`` — тоже терминальные.

    ``INTERACTIVE`` (BOB-083 .3) — живой двусторонний сеанс: менеджер держит запущенный
    процесс ``claude`` с открытым stdin, owner направляет его в реальном времени. Это
    ОТДЕЛЬНАЯ ветка жизненного цикла (не гейтед-путь план→исполнение): сессия сразу
    заводится в ``INTERACTIVE`` и завершается ТОЛЬКО прямым kill (``CANCELLED``) или
    честным провалом (``FAILED``). 🔴 Она НЕ ведёт в ``EXECUTING`` — гейт плана остаётся
    непробиваемым (единственный путь в ``EXECUTING`` — из ``PLAN_READY``).
    """

    PROPOSED = "proposed"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    EXECUTING = "executing"
    PR_OPEN = "pr_open"
    INTERACTIVE = "interactive"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


# Терминальные состояния — без исходящих переходов. PR_OPEN — УСПЕШНЫЙ терминал
# (BOB-042): открыв PR, Боб закончил; мерж делает owner асинхронно вне Боба, поэтому
# PR_OPEN не должен блокировать новую сессию. DONE сохранён как легаси-терминал
# (старые персистнутые сессии), но машиной больше не достижим.
_TERMINAL: frozenset[CodingSessionState] = frozenset(
    {
        CodingSessionState.PR_OPEN,
        CodingSessionState.DONE,
        CodingSessionState.CANCELLED,
        CodingSessionState.FAILED,
    }
)

# Прогресс-путь (без CANCELLED/FAILED, которые разрешены из любого нетерминального).
# 🔴 EXECUTING присутствует РОВНО в одном множестве — целей PLAN_READY: гейт плана
# непробиваем. PR_OPEN — терминал (см. _TERMINAL), исходящих переходов у него нет.
# INTERACTIVE (BOB-083 .3) — живой сеанс с ПУСТЫМ прогресс-множеством: он не ведёт
# по гейтед-пути (в частности, НЕ в EXECUTING — гейт плана непробиваем), а завершается
# только через kill/провал (CANCELLED/FAILED — они в _STOP_TARGETS, из любого
# нетерминального). Явная пустая запись документирует «только выход через stop».
_PROGRESS: dict[CodingSessionState, frozenset[CodingSessionState]] = {
    CodingSessionState.PROPOSED: frozenset({CodingSessionState.PLANNING}),
    CodingSessionState.PLANNING: frozenset({CodingSessionState.PLAN_READY}),
    CodingSessionState.PLAN_READY: frozenset({CodingSessionState.EXECUTING}),
    CodingSessionState.EXECUTING: frozenset({CodingSessionState.PR_OPEN}),
    CodingSessionState.INTERACTIVE: frozenset(),
}

# Из любого нетерминального состояния owner может остановить (CANCELLED) или сессия
# может честно провалиться (FAILED).
_STOP_TARGETS: frozenset[CodingSessionState] = frozenset(
    {CodingSessionState.CANCELLED, CodingSessionState.FAILED}
)


def is_terminal(state: CodingSessionState) -> bool:
    """Терминально ли ``state`` (``PR_OPEN`` / ``DONE`` / ``CANCELLED`` / ``FAILED``).

    ``PR_OPEN`` — успешный терминал (BOB-042): открыв PR, Боб завершил работу, мерж
    делает owner асинхронно вне Боба, поэтому такая сессия не блокирует новую.
    """
    return state in _TERMINAL


def can_transition(frm: CodingSessionState, to: CodingSessionState) -> bool:
    """Можно ли перевести сессию из ``frm`` в ``to`` (чистый предикат).

    Самопереход (``frm == to``) переходом НЕ считается. Терминальные состояния не
    имеют исходящих переходов. ``EXECUTING`` достижимо только из ``PLAN_READY``
    (гейт плана). ``CANCELLED`` / ``FAILED`` достижимы из любого нетерминального.
    """
    if is_terminal(frm):
        return False
    if to in _STOP_TARGETS:
        return True
    return to in _PROGRESS.get(frm, frozenset())


def can_start(state: CodingSessionState) -> bool:
    """Можно ли стартовать (PROPOSED → PLANNING) — только из ``PROPOSED``."""
    return can_transition(state, CodingSessionState.PLANNING)


def can_approve_plan(state: CodingSessionState) -> bool:
    """Можно ли апрувить план (ГЕЙТ ПЛАНА) — только из ``PLAN_READY``.

    Предикатная форма гейта: исполнение (``EXECUTING``) недостижимо без явного
    апрува из ``PLAN_READY``.
    """
    return can_transition(state, CodingSessionState.EXECUTING)


def can_stop(state: CodingSessionState) -> bool:
    """Можно ли остановить (kill-switch → CANCELLED) — из любого нетерминального."""
    return not is_terminal(state)
