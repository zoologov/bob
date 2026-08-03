# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты recovery-свипа осиротевших живых сессий (BOB-087.D5b, находка M5б).

Живая интерактивная сессия существует ТОЛЬКО пока жив процесс, который её держит. Если
Бобу перезапустили процесс (деплой, краш) посреди сеанса, ``stop`` не вызывался, и строка
навсегда осталась в нетерминальном ``INTERACTIVE``. Последствия, которые здесь под
тестами:

* ``CodingSessionStore.active()`` вечно отдаёт её как in-flight → гейтед-кодер отвечает
  «я уже в работе» на любую новую задачу;
* ``select_resumable`` эту строку пропускает (не терминальная) и молча поднимает БОЛЕЕ
  СТАРУЮ сессию — свежая работа в дереве, старая нить разговора.

Свип идёт на старте процесса и трогает РОВНО ``INTERACTIVE``: гейтед стадии
(``PLAN_READY`` и др.) переживают рестарт НАМЕРЕННО — owner апрувит план и после
перезапуска, — поэтому их сносить нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from bob.coding.entities import CodingSession
from bob.coding.state import CodingSessionState, is_terminal
from bob.interactive.resume_policy import select_resumable
from bob.interactive.usecases.recover_sessions import RecoverInteractiveSessions

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
_BRANCH = "bob/epic-bob-087"


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)
    saved: list[str] = field(default_factory=list)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session
        self.saved.append(session.id)

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


class _ExplodingStore(_FakeStore):
    async def active(self) -> tuple[CodingSession, ...]:
        raise RuntimeError("база недоступна")


class _Clock:
    def now(self) -> datetime:
        return _NOW


def _session(
    *,
    sid: str,
    state: CodingSessionState,
    claude_session_id: str | None = None,
    updated_at: datetime = _NOW - timedelta(hours=3),
) -> CodingSession:
    return CodingSession(
        id=sid,
        task="эпик BOB-087",
        state=state,
        branch=_BRANCH,
        created_at=_NOW - timedelta(days=1),
        updated_at=updated_at,
        worktree_path="/wt/epic-bob-087",
        claude_session_id=claude_session_id,
    )


def _build(*sessions: CodingSession) -> tuple[RecoverInteractiveSessions, _FakeStore]:
    store = _FakeStore(sessions={s.id: s for s in sessions})
    return RecoverInteractiveSessions(store=store, clock=_Clock()), store


@pytest.mark.asyncio
async def test_an_orphaned_interactive_row_is_moved_to_a_terminal_state() -> None:
    recover, store = _build(
        _session(sid="orphan", state=CodingSessionState.INTERACTIVE)
    )

    recovered = await recover.run()

    assert recovered == 1
    saved = store.sessions["orphan"]
    assert is_terminal(saved.state) is True
    assert saved.updated_at == _NOW


@pytest.mark.asyncio
async def test_the_recovered_row_stops_blocking_the_gated_coder() -> None:
    # 🔴 Наблюдаемое последствие: пока строка жива, ``active()`` отдаёт её как in-flight,
    # и гейтед-кодер вечно отвечает «я уже в работе».
    recover, store = _build(
        _session(sid="orphan", state=CodingSessionState.INTERACTIVE)
    )
    assert await store.active()  # до свипа — «сессия в работе»

    await recover.run()

    assert await store.active() == ()


@pytest.mark.asyncio
async def test_the_recovered_row_becomes_the_freshest_resume_candidate() -> None:
    # 🔴 Второе последствие: раньше свежая (но нетерминальная) строка кандидатом не была,
    # и «поднять» подняло бы БОЛЕЕ СТАРУЮ нить поверх свежей работы в дереве.
    recover, store = _build(
        _session(
            sid="old",
            state=CodingSessionState.CANCELLED,
            claude_session_id="claude-old",
            updated_at=_NOW - timedelta(days=2),
        ),
        _session(
            sid="orphan",
            state=CodingSessionState.INTERACTIVE,
            claude_session_id="claude-fresh",
            updated_at=_NOW - timedelta(minutes=5),
        ),
    )

    await recover.run()

    candidate = select_resumable(store.sessions.values(), branch=_BRANCH)
    assert candidate is not None
    assert candidate.claude_session_id == "claude-fresh"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        CodingSessionState.PLANNING,
        CodingSessionState.PLAN_READY,
        CodingSessionState.EXECUTING,
    ],
)
async def test_a_gated_session_stage_survives_the_sweep(
    state: CodingSessionState,
) -> None:
    # 🔴 Гейтед стадии переживают рестарт НАМЕРЕННО (owner апрувит план и назавтра) —
    # свип узкий: он про сессию, привязанную к УМЕРШЕМУ процессу, а не про любую живую.
    recover, store = _build(_session(sid="gated", state=state))

    recovered = await recover.run()

    assert recovered == 0
    assert store.sessions["gated"].state is state
    assert store.saved == []


@pytest.mark.asyncio
async def test_an_already_terminal_row_is_left_alone() -> None:
    recover, store = _build(
        _session(sid="done", state=CodingSessionState.CANCELLED)
    )

    assert await recover.run() == 0
    assert store.saved == []


@pytest.mark.asyncio
async def test_an_empty_store_is_a_no_op() -> None:
    recover, store = _build()

    assert await recover.run() == 0
    assert store.saved == []


@pytest.mark.asyncio
async def test_a_store_fault_never_blocks_the_boot() -> None:
    # Свип идёт на СТАРТЕ процесса: его сбой не смеет уронить загрузку Боба.
    recover = RecoverInteractiveSessions(store=_ExplodingStore(), clock=_Clock())

    assert await recover.run() == 0
