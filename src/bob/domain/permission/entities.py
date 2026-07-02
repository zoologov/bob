# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=permission

"""Доменный дата-класс permission-request — immutable value-object (BOB-052 .1).

``PermissionRequest`` — один pending-запрос привилегии: кто просит (не-owner), что
именно (человекочитаемо ``what`` + вид ``kind``), исходный текст запроса
(``request_text`` — нужен, чтобы исполнить запрос на approve в .3), его состояние
(:class:`PermissionState`) и время создания. ``frozen, slots``: без I/O, без часов —
:meth:`with_state` возвращает новый объект, так домен детерминирован и тестируем без
``datetime.now``. Персист — за адаптером ``SqlitePermissionRequestStore`` в
infrastructure, так домен остаётся I/O-free.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime  # noqa: TC003 — runtime-needed for the frozen field type
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.permission.state import PermissionState

__all__ = ["PermissionRequest"]


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """Pending-запрос привилегии от не-авторизованного участника.

    ``requester_id`` / ``requester_name`` — кто просит (не owner). ``request_text`` —
    исходное сообщение, сохранённое дословно, чтобы на approve Боб исполнил именно
    его. ``kind`` — вид привилегии (``tool`` | ``internal`` | ``owner_data``).
    ``what`` — человекочитаемое описание для owner-нотиса («показать задачи проекта»).
    ``created_at`` — timezone-aware метка (инжектится, не берётся из часов домена).
    """

    id: str
    requester_id: int
    requester_name: str
    request_text: str
    kind: str
    what: str
    state: PermissionState
    created_at: datetime

    def with_state(self, state: PermissionState) -> PermissionRequest:
        """Вернуть копию с новым ``state`` (остальные поля без изменений)."""
        return replace(self, state=state)
