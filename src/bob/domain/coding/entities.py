# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding-domain

"""Доменный дата-класс coding-сессии — immutable value-object (BOB-039 .1).

``CodingSession`` — одна гейтед сессия «Боб запускает Claude Code»: задача owner'а,
её состояние (:class:`CodingSessionState`), изолированная ветка/worktree, собранный
план и URL открытого PR. ``frozen, slots``: без I/O, без часов — час инжектится
параметром ``at`` в мутаторы, так домен детерминирован и тестируем без
``datetime.now``. Мутаторы (``with_state`` / ``with_plan`` / ``with_worktree`` /
``with_pr_url``) возвращают новый объект и обновляют ``updated_at``; персист — за
портом :class:`bob.domain.ports.CodingSessionStore`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003 — runtime-needed for the frozen field type
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.coding.state import CodingSessionState

__all__ = ["CodingSession"]


@dataclass(frozen=True, slots=True)
class CodingSession:
    """Гейтед сессия «Боб запускает Claude Code» — что делаем, где и на какой стадии.

    ``task`` — исходная формулировка owner'а. ``branch`` — безопасное имя ветки
    (``bob/<slug>``, см. :func:`bob.domain.coding.naming.worktree_branch`).
    ``worktree_path`` появляется после создания изолированного worktree; ``plan`` —
    после plan-mode прогона; ``pr_url`` — после открытия PR. ``created_at`` /
    ``updated_at`` — timezone-aware метки (инжектятся, не берутся из часов домена).
    """

    id: str
    task: str
    state: CodingSessionState
    branch: str
    created_at: datetime
    updated_at: datetime
    worktree_path: str | None = None
    plan: str | None = None
    pr_url: str | None = None

    def with_state(
        self, state: CodingSessionState, *, at: datetime
    ) -> CodingSession:
        """Вернуть копию с новым ``state`` и обновлённым ``updated_at``."""
        return replace(self, state=state, updated_at=at)

    def with_plan(self, plan: str, *, at: datetime) -> CodingSession:
        """Вернуть копию с собранным ``plan`` и обновлённым ``updated_at``."""
        return replace(self, plan=plan, updated_at=at)

    def with_worktree(self, worktree_path: str, *, at: datetime) -> CodingSession:
        """Вернуть копию с путём worktree и обновлённым ``updated_at``."""
        return replace(self, worktree_path=worktree_path, updated_at=at)

    def with_pr_url(self, pr_url: str, *, at: datetime) -> CodingSession:
        """Вернуть копию с URL открытого PR и обновлённым ``updated_at``."""
        return replace(self, pr_url=pr_url, updated_at=at)
