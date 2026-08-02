# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты SqliteCodingSessionStore — персист coding-сессий (BOB-039 .1).

Round-trip save→get восстанавливает сессию (состояние, ветка, worktree, план,
pr_url, времена); UPSERT по id; неизвестный id → None; active() возвращает только
нетерминальные сессии; выживание после рестарта.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.adapters.session_store import (
    SqliteCodingSessionStore,
)
from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo

if TYPE_CHECKING:
    from pathlib import Path

_T0 = datetime(2026, 6, 26, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 26, 11, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


def _session(
    sid: str = "cs1",
    *,
    state: CodingSessionState = CodingSessionState.PROPOSED,
    worktree_path: str | None = None,
    plan: str | None = None,
    pr_url: str | None = None,
    claude_session_id: str | None = None,
) -> CodingSession:
    return CodingSession(
        id=sid,
        task="починить парсер",
        state=state,
        branch="bob/fix-parser",
        created_at=_T0,
        updated_at=_T1,
        worktree_path=worktree_path,
        plan=plan,
        pr_url=pr_url,
        claude_session_id=claude_session_id,
    )


async def test_get_unknown_returns_none(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    assert await store.get("nope") is None


async def test_save_round_trips_full_session(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    session = _session(
        state=CodingSessionState.PR_OPEN,
        worktree_path="/work/wt/cs1",
        plan="1. читаю 2. правлю",
        pr_url="https://github.com/o/r/pull/7",
        claude_session_id="sess-abc",
    )

    await store.save(session)
    loaded = await store.get("cs1")

    assert loaded == session


async def test_save_round_trips_claude_session_id(repo: SqliteMemoryRepo) -> None:
    # BOB-087.D1: the claude session id survives the round-trip so a later /code can
    # look it up for --resume. A session without one round-trips as None (byte-identical
    # to a pre-D1 row).
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("with", claude_session_id="sess-9"))
    await store.save(_session("without"))

    with_id = await store.get("with")
    without_id = await store.get("without")

    assert with_id is not None
    assert with_id.claude_session_id == "sess-9"
    assert without_id is not None
    assert without_id.claude_session_id is None


async def test_save_upserts_on_id(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session(state=CodingSessionState.PROPOSED))

    await store.save(_session(state=CodingSessionState.PLAN_READY, plan="готов план"))
    loaded = await store.get("cs1")

    assert loaded is not None
    assert loaded.state is CodingSessionState.PLAN_READY
    assert loaded.plan == "готов план"


async def test_active_returns_only_non_terminal(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("a", state=CodingSessionState.EXECUTING))
    await store.save(_session("b", state=CodingSessionState.DONE))
    await store.save(_session("c", state=CodingSessionState.CANCELLED))
    await store.save(_session("d", state=CodingSessionState.FAILED))
    await store.save(_session("e", state=CodingSessionState.PLAN_READY))

    active = await store.active()

    assert tuple(sorted(s.id for s in active)) == ("a", "e")


async def test_active_skips_unparseable_row(repo: SqliteMemoryRepo) -> None:
    # 🔴 Резилентность (BOB-078 D): одна битая строка в coding_session (напр. state в
    # верхнем регистре 'CANCELLED' — не валидный enum, валиден 'cancelled') НЕ должна
    # ронять весь active() — битую пропускаем (лог), валидные возвращаем. Иначе
    # coding-router бросает на КАЖДОМ сообщении и Боб глохнет на owner.
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("good", state=CodingSessionState.EXECUTING))
    await repo.connection.execute(
        "INSERT INTO coding_session (id, task, state, branch, created_at, updated_at, "
        "worktree_path, plan, pr_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("bad", "t", "CANCELLED", "b", _T0.isoformat(), _T1.isoformat(), None, None, None),
    )
    await repo.connection.commit()

    active = await store.active()

    assert tuple(s.id for s in active) == ("good",)


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    session = _session(
        state=CodingSessionState.EXECUTING,
        worktree_path="/work/wt/cs1",
        plan="план",
        pr_url=None,
    )

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteCodingSessionStore(first).save(session)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteCodingSessionStore(second).get("cs1")
    await second.close()

    assert loaded == session


# --- by_branch: the narrow resumable-session lookup (BOB-087.D3) ---------------


async def test_by_branch_returns_every_state_on_that_branch(repo: SqliteMemoryRepo) -> None:
    # 🔴 Unlike ``active()``, the lookup filters by BRANCH ONLY and returns EVERY state
    # (terminal included) — terminality is the pure domain policy's call
    # (``select_resumable``), not the store's, so the two can never drift.
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("live", state=CodingSessionState.INTERACTIVE))
    await store.save(_session("done", state=CodingSessionState.CANCELLED))

    found = await store.by_branch("bob/fix-parser")

    assert {s.id for s in found} == {"live", "done"}


async def test_by_branch_ignores_other_branches(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("mine", state=CodingSessionState.CANCELLED))
    other = CodingSession(
        id="theirs",
        task="другое",
        state=CodingSessionState.CANCELLED,
        branch="bob/epic-other",
        created_at=_T0,
        updated_at=_T1,
    )
    await store.save(other)

    found = await store.by_branch("bob/fix-parser")

    assert tuple(s.id for s in found) == ("mine",)


async def test_by_branch_unknown_branch_is_empty(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("mine", state=CodingSessionState.CANCELLED))

    assert await store.by_branch("bob/epic-nope") == ()


async def test_by_branch_round_trips_the_claude_session_id(repo: SqliteMemoryRepo) -> None:
    store = SqliteCodingSessionStore(repo)
    await store.save(
        _session("s", state=CodingSessionState.CANCELLED, claude_session_id="claude-9")
    )

    found = await store.by_branch("bob/fix-parser")

    assert [s.claude_session_id for s in found] == ["claude-9"]


async def test_by_branch_skips_an_unparseable_row(repo: SqliteMemoryRepo) -> None:
    # Same resilience as ``active()``: one corrupt row must not blow up the lookup that
    # runs on an owner's /resume command.
    store = SqliteCodingSessionStore(repo)
    await store.save(_session("good", state=CodingSessionState.CANCELLED))
    await repo.connection.execute(
        "INSERT INTO coding_session (id, task, state, branch, created_at, updated_at, "
        "worktree_path, plan, pr_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "bad",
            "t",
            "CANCELLED",
            "bob/fix-parser",
            _T0.isoformat(),
            _T1.isoformat(),
            None,
            None,
            None,
        ),
    )
    await repo.connection.commit()

    found = await store.by_branch("bob/fix-parser")

    assert tuple(s.id for s in found) == ("good",)
