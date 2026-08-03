# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the boot-time sweep of orphaned live sessions (BOB-087.D5b, M5б).

Driven against a REAL SQLite store (not a fake): the whole point of the finding is what a
restart leaves BEHIND IN THE DATABASE. A row stuck in ``INTERACTIVE`` survives forever,
and the observable damage is that the gated coder keeps answering «я уже в работе».

The sweep is wired UNCONDITIONALLY (see ``_build_interactive_recovery``): such a row can
only exist because the interactive terminal once ran, the process that could close it is
gone, and it must not keep blocking the gated coder after the owner flips the flag back
off. With no such row it writes nothing at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.adapters.session_store import SqliteCodingSessionStore
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.runtime.wiring.coding import _build_interactive_recovery

if TYPE_CHECKING:
    from pathlib import Path

    from bob.infrastructure.persistence import SqliteConnection
    from bob.kernel.ports import Clock

_T0 = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class _StubClock:
    def now(self) -> datetime:
        return _NOW


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


def _session(sid: str, state: CodingSessionState) -> CodingSession:
    return CodingSession(
        id=sid,
        task="эпик BOB-087",
        state=state,
        branch="bob/epic-bob-087",
        created_at=_T0,
        updated_at=_T0,
        worktree_path="/wt/epic-bob-087",
        claude_session_id="claude-42",
    )


def _recovery(repo: SqliteMemoryRepo) -> object:
    return _build_interactive_recovery(
        repo=cast("SqliteConnection", repo), clock=cast("Clock", _StubClock())
    )


async def test_boot_closes_a_row_left_interactive_by_a_restart(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("orphan", CodingSessionState.INTERACTIVE))

    recovered = await _recovery(repo).run()  # type: ignore[attr-defined]

    assert recovered == 1
    saved = await store.get("orphan")
    assert saved is not None
    assert is_terminal(saved.state) is True
    # 🔴 The damage the finding named: the gated coder no longer sees an in-flight session.
    assert await store.active() == ()


async def test_boot_leaves_a_gated_stage_in_flight(repo: SqliteMemoryRepo) -> None:
    # An awaiting-approval session SHOULD survive a restart — the owner approves later.
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("gated", CodingSessionState.PLAN_READY))

    assert await _recovery(repo).run() == 0  # type: ignore[attr-defined]

    still_active = await store.active()
    assert [s.id for s in still_active] == ["gated"]


async def test_boot_with_nothing_recorded_writes_nothing(repo: SqliteMemoryRepo) -> None:
    # The flags-off path: no interactive row was ever written → a pure no-op.
    assert await _recovery(repo).run() == 0  # type: ignore[attr-defined]
    assert await SqliteCodingSessionStore(repo).active() == ()


async def test_the_sweep_is_idempotent(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("orphan", CodingSessionState.INTERACTIVE))

    first = await _recovery(repo).run()  # type: ignore[attr-defined]
    second = await _recovery(repo).run()  # type: ignore[attr-defined]

    assert (first, second) == (1, 0)
