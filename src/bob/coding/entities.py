# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Доменные value-объекты coding-сессии — что за сессия и чем кончилась команда.

``CodingSession`` — одна сессия «Боб запускает Claude Code»: задача owner'а,
её состояние (:class:`CodingSessionState`), изолированная ветка/worktree, собранный
план и URL открытого PR. ``frozen, slots``: без I/O, без часов — час инжектится
параметром ``at`` в мутаторы, так домен детерминирован и тестируем без
``datetime.now``. Мутаторы (``with_state`` / ``with_plan`` / ``with_worktree`` /
``with_pr_url``) возвращают новый объект и обновляют ``updated_at``; персист — за
портом :class:`bob.coding.ports.CodingSessionStore`.

``CodingOutcome`` — итог ОДНОЙ команды над сессией. 🔴 BOB-087.E (bob-6u2): раньше он
жил внутри монолита :mod:`bob.coding.usecases.coding_assistant`, хотя это чистый
value-object и ОБЩИЙ словарь двух bounded context'ов — гейтед-кодера и живого
терминала (:mod:`bob.interactive`). Живой терминал теперь отдельный узел графа и
обязан опираться на ОБЩУЮ доменную поверхность coding, а не на его use-case; поэтому
дата-класс переехал сюда, к своему соседу ``CodingSession``. Старый путь импорта
сохранён ре-экспортом в ``coding_assistant`` — снаружи ничего не изменилось.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003 — runtime-needed for the frozen field type
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.coding.state import CodingSessionState

__all__ = ["CodingOutcome", "CodingSession"]


@dataclass(frozen=True, slots=True)
class CodingSession:
    """Гейтед сессия «Боб запускает Claude Code» — что делаем, где и на какой стадии.

    ``task`` — исходная формулировка owner'а. ``branch`` — безопасное имя ветки
    (``bob/<slug>``, см. :func:`bob.coding.naming.worktree_branch`).
    ``worktree_path`` появляется после создания изолированного worktree; ``plan`` —
    после plan-mode прогона; ``pr_url`` — после открытия PR. ``claude_session_id``
    (BOB-087.D1) — id сессии, который отдал ``claude`` в init-событии stream-json;
    хранится, чтобы позже (D3) можно было возобновить сеанс через ``--resume`` (None,
    пока сеанс не отдал id). ``created_at`` / ``updated_at`` — timezone-aware метки
    (инжектятся, не берутся из часов домена).
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
    claude_session_id: str | None = None

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

    def with_claude_session_id(
        self, claude_session_id: str, *, at: datetime
    ) -> CodingSession:
        """Вернуть копию с id claude-сессии (для ``--resume``) и обновлённым ``updated_at``.

        BOB-087.D1: сохраняет session-id из init-события stream-json, чтобы позже сеанс
        можно было возобновить по id.
        """
        return replace(self, claude_session_id=claude_session_id, updated_at=at)


@dataclass(frozen=True, slots=True)
class CodingOutcome:
    """Итог одной команды: успех/отказ, owner-сообщение и итоговая сессия.

    ``ok`` ложно при отказе authz / нелегальной команде / провале. ``message`` —
    короткий owner-текст (уже отправлен через нотификатор, кроме «тихого» отказа
    не-owner'у). ``session`` — итоговая сессия (``None``, если её нет/не создавалась).
    """

    ok: bool
    message: str
    session: CodingSession | None = None
