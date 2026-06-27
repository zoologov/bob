# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты индикатора работы coding-сессии (BOB-046 .2).

Покрыто:
* typing-keepalive ОБОРАЧИВАЕТ длинные прогоны (plan + execute): индикатор активен
  ВО ВРЕМЯ прогона раннера и закрывается после;
* одно editable сообщение-статус: SENT один раз (``open``) и РЕДАКТИРУЕТСЯ по фазам
  (``update``: план → выполняю → PR), а не N новых сообщений;
* на провале (исключение раннера / нет правок) статус финализируется в ошибку;
* незавязанные сеймы (typing/panel не инъектированы) деградируют без падения и без
  статус-сообщения.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.usecases.coding_assistant import CodingAssistant
from bob.domain.coding import session_voice
from bob.domain.coding.state import CodingSessionState, is_terminal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping
    from contextlib import AbstractAsyncContextManager

    from bob.domain.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


@dataclass
class _LoggingRunner:
    """Async-generator раннер, пишущий маркер прогона в общий лог (для порядка событий)."""

    log: list[str]
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        self.log.append(f"run:{mode}")
        error = self.errors.get(mode)
        if error is not None:
            raise error
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeTyping:
    """Сейм typing-keepalive: пишет enter/exit в общий лог; считает активность."""

    log: list[str]
    depth: int = 0
    max_depth: int = 0

    def __call__(self) -> AbstractAsyncContextManager[None]:
        return self._cm()

    @contextlib.asynccontextmanager
    async def _cm(self) -> AsyncIterator[None]:
        self.log.append("typing:enter")
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        try:
            yield
        finally:
            self.depth -= 1
            self.log.append("typing:exit")


@dataclass
class _FakePanel:
    """Сейм статус-панели: фиксирует одно ``open`` и N ``update`` (без спама send)."""

    opens: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)

    async def open(self, text: str) -> None:
        self.opens.append(text)

    async def update(self, text: str) -> None:
        self.updates.append(text)


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    committed: bool = True

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return self.committed

    async def remove(self, path: str) -> None:
        self.removed.append(path)


@dataclass
class _FakeStore:
    sessions: dict[str, CodingSession] = field(default_factory=dict)

    async def save(self, session: CodingSession) -> None:
        self.sessions[session.id] = session

    async def get(self, session_id: str) -> CodingSession | None:
        return self.sessions.get(session_id)

    async def active(self) -> tuple[CodingSession, ...]:
        ordered = sorted(self.sessions.values(), key=lambda s: (s.created_at, s.id))
        return tuple(s for s in ordered if not is_terminal(s.state))


@dataclass
class _FakePROpener:
    url: str = "https://github.com/x/bob/pull/7"

    async def open(self, branch: str, title: str, body: str) -> str:
        return self.url


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _FakeOwner:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


@dataclass
class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _plan_events() -> dict[str, list[Mapping[str, object]]]:
    return {"plan": [{"type": "result", "subtype": "success", "result": "Итоговый план"}]}


def _execute_events() -> list[Mapping[str, object]]:
    return [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "f.py"}}
                ]
            },
        },
        {"type": "result", "subtype": "success"},
    ]


@dataclass
class _Rig:
    assistant: CodingAssistant
    worktree: _FakeWorktree
    store: _FakeStore
    notifier: _FakeNotifier
    typing: _FakeTyping | None
    panel: _FakePanel | None
    log: list[str]


def _build(
    *,
    wire_indicators: bool = True,
    plan_error: Exception | None = None,
    committed: bool = True,
) -> _Rig:
    log: list[str] = []
    errors = {"plan": plan_error} if plan_error is not None else {}
    runner = _LoggingRunner(
        log=log, events={**_plan_events(), "acceptEdits": _execute_events()}, errors=errors
    )
    worktree = _FakeWorktree(committed=committed)
    store = _FakeStore()
    notifier = _FakeNotifier()
    typing = _FakeTyping(log=log) if wire_indicators else None
    panel = _FakePanel() if wire_indicators else None
    assistant = CodingAssistant(
        runner=runner,
        worktree=worktree,
        store=store,
        pr_opener=_FakePROpener(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        typing_keepalive=typing,
        status_panel=panel,
    )
    return _Rig(assistant, worktree, store, notifier, typing, panel, log)


@pytest.mark.asyncio
async def test_typing_keepalive_wraps_plan_and_execute_runs() -> None:
    rig = _build()
    assert rig.typing is not None

    await rig.assistant.start("Добавить ручку health", _OWNER_ID)
    await rig.assistant.approve_plan(_OWNER_ID)

    # The typing indicator opens BEFORE each run and closes AFTER it — both the plan
    # and the execute waits are wrapped, and the indicator is never left dangling.
    assert rig.log == [
        "typing:enter",
        "run:plan",
        "typing:exit",
        "typing:enter",
        "run:acceptEdits",
        "typing:exit",
    ]
    assert rig.typing.depth == 0
    assert rig.typing.max_depth == 1


@pytest.mark.asyncio
async def test_status_panel_sent_once_and_edited_through_phases() -> None:
    rig = _build()
    assert rig.panel is not None

    await rig.assistant.start("Добавить ручку health", _OWNER_ID)
    await rig.assistant.approve_plan(_OWNER_ID)

    # ONE message is opened, then EDITED through the phases — not N new messages.
    assert rig.panel.opens == [session_voice.panel_planning()]
    assert rig.panel.updates == [
        session_voice.panel_plan_ready(),
        session_voice.panel_executing(),
        session_voice.panel_pr(),
    ]


@pytest.mark.asyncio
async def test_status_panel_finalizes_to_error_on_runner_failure() -> None:
    rig = _build(plan_error=RuntimeError("boom"))
    assert rig.panel is not None

    outcome = await rig.assistant.start("Добавить ручку health", _OWNER_ID)

    assert outcome.ok is False
    assert rig.panel.opens == [session_voice.panel_planning()]
    assert rig.panel.updates == [session_voice.panel_failed()]


@pytest.mark.asyncio
async def test_status_panel_finalizes_to_error_when_no_changes() -> None:
    rig = _build(committed=False)
    assert rig.panel is not None

    await rig.assistant.start("Добавить ручку health", _OWNER_ID)
    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    # No PR phase; the panel finalizes to the error state on an empty run.
    assert rig.panel.updates[-1] == session_voice.panel_failed()
    assert session_voice.panel_pr() not in rig.panel.updates


@pytest.mark.asyncio
async def test_unwired_indicators_degrade_gracefully() -> None:
    # No typing/panel injected → no status message, no typing, and NO crash; the gated
    # flow (plan → approve → PR) still completes exactly as before.
    rig = _build(wire_indicators=False)

    started = await rig.assistant.start("Добавить ручку health", _OWNER_ID)
    approved = await rig.assistant.approve_plan(_OWNER_ID)

    assert started.ok is True
    assert approved.ok is True
    assert approved.session is not None
    assert approved.session.state is CodingSessionState.PR_OPEN
    # No typing markers leaked into the run log when the seam is unwired.
    assert rig.log == ["run:plan", "run:acceptEdits"]
