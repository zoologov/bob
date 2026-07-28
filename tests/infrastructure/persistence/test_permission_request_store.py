# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqlitePermissionRequestStore — персист permission-request (BOB-052 .1).

Round-trip save→active восстанавливает запрос (состояние, requester, исходный текст,
kind/what, время); ``set_state`` меняет состояние; ``active_for`` фильтрует по
просящему; ``active`` отдаёт только PENDING; миграция идемпотентна (повторный
``ensure_schema`` — no-op).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.adapters.permission_request_store import (
    SqlitePermissionRequestStore,
)
from bob.social.permission.entities import PermissionRequest
from bob.social.permission.state import PermissionState

if TYPE_CHECKING:
    from pathlib import Path

_T0 = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


def _request(
    rid: str = "pr1",
    *,
    requester_id: int = 42,
    state: PermissionState = PermissionState.PENDING,
) -> PermissionRequest:
    return PermissionRequest(
        id=rid,
        requester_id=requester_id,
        requester_name="Норман",
        request_text="покажи задачи проекта",
        kind="owner_data",
        what="показать задачи проекта",
        state=state,
        created_at=_T0,
    )


async def test_save_round_trips_through_active(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    request = _request()

    await store.save(request)
    loaded = await store.active()

    assert loaded == (request,)


async def test_active_for_filters_by_requester(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    await store.save(_request("a", requester_id=1))
    await store.save(_request("b", requester_id=2))

    for_one = await store.active_for(1)

    assert [r.id for r in for_one] == ["a"]


async def test_active_excludes_resolved_requests(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    await store.save(_request("pending"))
    await store.save(_request("approved", state=PermissionState.APPROVED))
    await store.save(_request("denied", state=PermissionState.DENIED))
    await store.save(_request("expired", state=PermissionState.EXPIRED))

    active = await store.active()

    assert [r.id for r in active] == ["pending"]


async def test_set_state_transitions_the_persisted_request(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    await store.save(_request())

    await store.set_state("pr1", PermissionState.APPROVED)

    # No longer active (PENDING-only), but the row persists with the new state.
    assert await store.active() == ()
    for_requester = await store.active_for(42)
    assert for_requester == ()


async def test_set_state_on_unknown_id_is_a_noop(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    await store.set_state("missing", PermissionState.DENIED)
    assert await store.active() == ()


async def test_save_upserts_on_id(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    await store.save(_request())
    await store.save(_request(state=PermissionState.DENIED))
    assert await store.active() == ()


async def test_ensure_schema_is_idempotent(repo: SqliteMemoryRepo) -> None:
    store = SqlitePermissionRequestStore(repo)
    # initialize() already created the table; calling ensure_schema again must not raise.
    await store.ensure_schema()
    await store.ensure_schema()
    await store.save(_request())
    assert len(await store.active()) == 1


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    repo1 = SqliteMemoryRepo(db)
    await repo1.initialize()
    await SqlitePermissionRequestStore(repo1).save(_request())
    await repo1.close()

    repo2 = SqliteMemoryRepo(db)
    await repo2.initialize()
    active = await SqlitePermissionRequestStore(repo2).active()
    await repo2.close()

    assert [r.id for r in active] == ["pr1"]
