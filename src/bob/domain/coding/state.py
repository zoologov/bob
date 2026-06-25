# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

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
на уровне use-case (.3). Мержа в машине нет — Боб открывает PR и останавливается
(``PR_OPEN → DONE`` фиксирует «PR открыт», мерж делает owner вне Боба).
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
    ``EXECUTING`` (план одобрен, идёт исполнение в worktree) → ``PR_OPEN`` (PR открыт,
    ждёт мержа owner) → терминальный ``DONE``; ``CANCELLED`` (kill-switch owner'а из
    любого нетерминального) и ``FAILED`` (честный провал/таймаут) — терминальные.
    """

    PROPOSED = "proposed"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    EXECUTING = "executing"
    PR_OPEN = "pr_open"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


# Терминальные состояния — без исходящих переходов.
_TERMINAL: frozenset[CodingSessionState] = frozenset(
    {
        CodingSessionState.DONE,
        CodingSessionState.CANCELLED,
        CodingSessionState.FAILED,
    }
)

# Прогресс-путь (без CANCELLED/FAILED, которые разрешены из любого нетерминального).
# 🔴 EXECUTING присутствует РОВНО в одном множестве — целей PLAN_READY: гейт плана
# непробиваем. DONE достижимо только из PR_OPEN.
_PROGRESS: dict[CodingSessionState, frozenset[CodingSessionState]] = {
    CodingSessionState.PROPOSED: frozenset({CodingSessionState.PLANNING}),
    CodingSessionState.PLANNING: frozenset({CodingSessionState.PLAN_READY}),
    CodingSessionState.PLAN_READY: frozenset({CodingSessionState.EXECUTING}),
    CodingSessionState.EXECUTING: frozenset({CodingSessionState.PR_OPEN}),
    CodingSessionState.PR_OPEN: frozenset({CodingSessionState.DONE}),
}

# Из любого нетерминального состояния owner может остановить (CANCELLED) или сессия
# может честно провалиться (FAILED).
_STOP_TARGETS: frozenset[CodingSessionState] = frozenset(
    {CodingSessionState.CANCELLED, CodingSessionState.FAILED}
)


def is_terminal(state: CodingSessionState) -> bool:
    """Терминально ли ``state`` (``DONE`` / ``CANCELLED`` / ``FAILED``)."""
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
