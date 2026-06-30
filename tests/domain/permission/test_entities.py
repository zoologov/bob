# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты PermissionRequest — immutable pending-запрос привилегии (BOB-052 .1).

Frozen value-object: ``with_state`` возвращает копию с новым состоянием, не мутируя
оригинал; остальные поля (включая исходный ``request_text``, нужный для исполнения на
approve) сохраняются.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.domain.permission.entities import PermissionRequest
from bob.domain.permission.state import PermissionState

_T0 = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _request(state: PermissionState = PermissionState.PENDING) -> PermissionRequest:
    return PermissionRequest(
        id="pr1",
        requester_id=42,
        requester_name="Норман",
        request_text="покажи задачи проекта",
        kind="owner_data",
        what="показать задачи проекта",
        state=state,
        created_at=_T0,
    )


def test_carries_original_request_text_for_fulfilment() -> None:
    request = _request()
    # The original message is preserved so .3 can re-run it on approve.
    assert request.request_text == "покажи задачи проекта"
    assert request.what == "показать задачи проекта"
    assert request.kind == "owner_data"


def test_with_state_returns_a_new_object_with_the_new_state() -> None:
    pending = _request()

    approved = pending.with_state(PermissionState.APPROVED)

    assert approved.state is PermissionState.APPROVED
    assert approved.id == pending.id
    assert approved.requester_id == pending.requester_id
    assert approved.request_text == pending.request_text
    assert approved.created_at == pending.created_at


def test_with_state_does_not_mutate_the_original() -> None:
    pending = _request()

    pending.with_state(PermissionState.DENIED)

    assert pending.state is PermissionState.PENDING


def test_is_frozen() -> None:
    request = _request()
    with pytest.raises((AttributeError, TypeError)):
        request.state = PermissionState.APPROVED  # type: ignore[misc]
