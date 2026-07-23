# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты доменного дата-класса CodingSession (BOB-039 .1).

immutable (frozen+slots); чистые мутаторы with_state/with_plan/with_worktree/
with_pr_url возвращают новый объект и обновляют updated_at (детерминированно — час
инжектится параметром, домен не зовёт datetime.now).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState

_T0 = datetime(2026, 6, 26, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 26, 11, 0, tzinfo=UTC)


def _session() -> CodingSession:
    return CodingSession(
        id="cs1",
        task="починить парсер",
        state=CodingSessionState.PROPOSED,
        branch="bob/fix-parser",
        created_at=_T0,
        updated_at=_T0,
    )


def test_session_is_frozen() -> None:
    session = _session()
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.state = CodingSessionState.PLANNING  # type: ignore[misc]


def test_optional_fields_default_to_none() -> None:
    session = _session()
    assert session.worktree_path is None
    assert session.plan is None
    assert session.pr_url is None


def test_with_state_returns_new_session_and_bumps_updated_at() -> None:
    session = _session()

    moved = session.with_state(CodingSessionState.PLANNING, at=_T1)

    assert moved is not session
    assert moved.state is CodingSessionState.PLANNING
    assert moved.updated_at == _T1
    assert moved.created_at == _T0
    # исходный объект не изменён
    assert session.state is CodingSessionState.PROPOSED


def test_with_plan_records_plan() -> None:
    session = _session()

    planned = session.with_plan("1. читаю 2. правлю", at=_T1)

    assert planned.plan == "1. читаю 2. правлю"
    assert planned.updated_at == _T1


def test_with_worktree_records_path() -> None:
    session = _session()

    located = session.with_worktree("/work/wt/cs1", at=_T1)

    assert located.worktree_path == "/work/wt/cs1"
    assert located.updated_at == _T1


def test_with_pr_url_records_url() -> None:
    session = _session()

    opened = session.with_pr_url("https://github.com/o/r/pull/7", at=_T1)

    assert opened.pr_url == "https://github.com/o/r/pull/7"
    assert opened.updated_at == _T1
