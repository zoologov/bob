# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Coding-сессия — чистый домен «Боб запускает Claude Code» (без I/O; BOB-039).

Гейтед персист-процесс под owner-контролем (тот же паттерн, что Goal Engine
BOB-015): сессия (:class:`CodingSession`) как immutable value-object, машина
состояний (:class:`CodingSessionState` + чистые предикаты переходов) с
НЕПРОБИВАЕМЫМ гейтом плана (``EXECUTING`` только из ``PLAN_READY``), чистый
:func:`narrate` (stream-json событие Claude Code → русская нарратив-строка / шум →
``None``) и :func:`worktree_branch` (безопасное имя ветки ``bob/<slug>``).

Персист — за портом :class:`bob.coding.ports.CodingSessionStore` (адаптер
``SqliteCodingSessionStore`` в infrastructure); раннер/worktree/PR (.2) и use-case
``CodingAssistant`` (.3) строятся поверх. Боб НИКОГДА не мержит — машина
останавливается на ``PR_OPEN``, мерж делает owner вне Боба.
"""

from __future__ import annotations

from bob.coding.entities import CodingSession
from bob.coding.naming import worktree_branch
from bob.coding.narrate import narrate
from bob.coding.state import (
    CodingSessionState,
    can_approve_plan,
    can_start,
    can_stop,
    can_transition,
    is_terminal,
)

__all__ = [
    "CodingSession",
    "CodingSessionState",
    "can_approve_plan",
    "can_start",
    "can_stop",
    "can_transition",
    "is_terminal",
    "narrate",
    "worktree_branch",
]
