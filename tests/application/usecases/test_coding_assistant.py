# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты CodingAssistant — гейтед оркестратор «Боб запускает Claude Code» (BOB-039 .3).

Покрыто (safety-инварианты под тестами):
* happy path: start → PLAN_READY (план показан, НЕ исполнен) → approve_plan →
  EXECUTING → нарратив → PR_OPEN (PR открыт, НЕ смержен);
* 🔴 не-owner получает отказ на КАЖДОЙ команде (нет сессии, нет исполнения);
* 🔴 approve_plan без плана / не из PLAN_READY — отказ, исполнения нет;
* 🔴 нет вызова мержа/пуша-в-main — единственное PR-действие это open;
* stop → CANCELLED + worktree убран; ошибка/таймаут раннера → FAILED + worktree убран;
* нарратив-строки доходят до нотификатора (gateway).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.application.usecases.coding_assistant import CodingAssistant
from bob.domain.coding.state import CodingSessionState, is_terminal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.domain.coding.entities import CodingSession

_OWNER_ID = 27468732
_STRANGER_ID = 555
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


@dataclass
class _FakeRunner:
    """Async-generator раннер: канон-события по режиму или исключение."""

    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        self.calls.append((workdir, prompt, mode))
        error = self.errors.get(mode)
        if error is not None:
            raise error
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        slug = branch.split("/", 1)[1]
        return f"/wt/{slug}"

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
    opens: list[tuple[str, str, str]] = field(default_factory=list)

    async def open(self, branch: str, title: str, body: str) -> str:
        self.opens.append((branch, title, body))
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
    moment: datetime = _NOW

    def now(self) -> datetime:
        return self.moment


def _ids() -> Callable[[], str]:
    counter = {"n": 0}

    def _factory() -> str:
        counter["n"] += 1
        return f"cs-{counter['n']}"

    return _factory


def _plan_events() -> dict[str, list[Mapping[str, object]]]:
    return {
        "plan": [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Шаг 1: правки"}]},
            },
            {"type": "result", "subtype": "success", "result": "Итоговый план"},
        ],
    }


def _execute_events() -> list[Mapping[str, object]]:
    return [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "foo.py"}}
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
    pr_opener: _FakePROpener
    notifier: _FakeNotifier
    runner: _FakeRunner


def _build(
    *,
    runner: _FakeRunner | None = None,
    worktree: _FakeWorktree | None = None,
    store: _FakeStore | None = None,
    pr_opener: _FakePROpener | None = None,
    notifier: _FakeNotifier | None = None,
) -> _Rig:
    runner = runner or _FakeRunner(events=_plan_events())
    worktree = worktree or _FakeWorktree()
    store = store or _FakeStore()
    pr_opener = pr_opener or _FakePROpener()
    notifier = notifier or _FakeNotifier()
    assistant = CodingAssistant(
        runner=runner,
        worktree=worktree,
        store=store,
        pr_opener=pr_opener,
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )
    return _Rig(assistant, worktree, store, pr_opener, notifier, runner)


@pytest.mark.asyncio
async def test_start_builds_plan_and_stops_at_plan_ready_not_executed() -> None:
    rig = _build()

    outcome = await rig.assistant.start("Добавить ручку health", _OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PLAN_READY
    # The worktree was created on a safe bob/<slug> branch and is KEPT (needed for approve).
    assert rig.worktree.created[0].startswith("bob/")
    assert rig.worktree.removed == []
    # The runner ran ONLY in plan mode — execution did NOT start.
    assert [mode for _, _, mode in rig.runner.calls] == ["plan"]
    # The plan reached the owner.
    assert any("Итоговый план" in text or "Шаг 1" in text for text in rig.notifier.sent)
    # Persisted at PLAN_READY with the collected plan.
    saved = await rig.store.active()
    assert len(saved) == 1
    assert saved[0].state is CodingSessionState.PLAN_READY
    assert saved[0].plan


@pytest.mark.asyncio
async def test_full_happy_path_approve_executes_narrates_and_opens_pr_no_merge() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    rig = _build(runner=runner)

    await rig.assistant.start("Починить парсер", _OWNER_ID)
    rig.notifier.sent.clear()
    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PR_OPEN
    assert outcome.session.pr_url == rig.pr_opener.url
    # Executed in the edit mode after approval.
    assert "acceptEdits" in [mode for _, _, mode in rig.runner.calls]
    # Narrative lines reached the gateway.
    assert any("правлю" in text for text in rig.notifier.sent)
    # 🔴 The ONLY PR action is open — exactly once, on the bob/<slug> branch; no merge.
    assert len(rig.pr_opener.opens) == 1
    assert rig.pr_opener.opens[0][0].startswith("bob/")
    assert not hasattr(rig.pr_opener, "merge")
    # The PR url was reported to the owner.
    assert any(rig.pr_opener.url in text for text in rig.notifier.sent)


@pytest.mark.asyncio
async def test_non_owner_refused_at_every_command_no_session_no_execution() -> None:
    rig = _build()

    start = await rig.assistant.start("что-нибудь", _STRANGER_ID)
    approve = await rig.assistant.approve_plan(_STRANGER_ID)
    stop = await rig.assistant.stop(_STRANGER_ID)
    status = await rig.assistant.status(_STRANGER_ID)

    for outcome in (start, approve, stop, status):
        assert outcome.ok is False
    # No worktree, no run, no PR, no owner message — a silent, side-effect-free refusal.
    assert rig.worktree.created == []
    assert rig.worktree.removed == []
    assert rig.runner.calls == []
    assert rig.pr_opener.opens == []
    assert rig.notifier.sent == []
    assert await rig.store.active() == ()


@pytest.mark.asyncio
async def test_approve_without_plan_is_refused_no_execution() -> None:
    rig = _build()

    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert rig.runner.calls == []
    assert rig.pr_opener.opens == []


@pytest.mark.asyncio
async def test_approve_from_non_plan_ready_state_is_refused() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    rig = _build(runner=runner)
    await rig.assistant.start("Задача", _OWNER_ID)
    await rig.assistant.approve_plan(_OWNER_ID)  # now PR_OPEN, not PLAN_READY
    rig.pr_opener.opens.clear()

    # A second approve has no PLAN_READY session to approve → refused, no new execution.
    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert rig.pr_opener.opens == []


@pytest.mark.asyncio
async def test_stop_cancels_and_removes_worktree() -> None:
    rig = _build()
    await rig.assistant.start("Задача", _OWNER_ID)

    outcome = await rig.assistant.stop(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.CANCELLED
    # The worktree was cleaned up — no leak.
    assert len(rig.worktree.removed) == 1
    assert await rig.store.active() == ()


@pytest.mark.asyncio
async def test_runner_error_marks_failed_and_removes_worktree() -> None:
    runner = _FakeRunner(errors={"plan": TimeoutError("claude timed out")})
    rig = _build(runner=runner)

    outcome = await rig.assistant.start("Задача", _OWNER_ID)

    assert outcome.ok is False
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.FAILED
    # The worktree was created then removed on failure — no leak.
    assert len(rig.worktree.created) == 1
    assert len(rig.worktree.removed) == 1
    assert await rig.store.active() == ()


@pytest.mark.asyncio
async def test_execute_runner_error_marks_failed_and_removes_worktree() -> None:
    runner = _FakeRunner(
        events=_plan_events(), errors={"acceptEdits": RuntimeError("boom")}
    )
    rig = _build(runner=runner)
    await rig.assistant.start("Задача", _OWNER_ID)

    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is False
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.FAILED
    assert rig.pr_opener.opens == []
    assert len(rig.worktree.removed) == 1
    assert await rig.store.active() == ()


@pytest.mark.asyncio
async def test_status_reports_state() -> None:
    rig = _build()
    idle = await rig.assistant.status(_OWNER_ID)
    assert idle.ok is True
    assert idle.session is None

    await rig.assistant.start("Задача", _OWNER_ID)
    rig.notifier.sent.clear()
    busy = await rig.assistant.status(_OWNER_ID)

    assert busy.session is not None
    assert busy.session.state is CodingSessionState.PLAN_READY
    assert any("plan_ready" in text for text in rig.notifier.sent)


@pytest.mark.asyncio
async def test_second_start_while_in_flight_is_refused() -> None:
    rig = _build()
    await rig.assistant.start("Первая", _OWNER_ID)
    rig.runner.calls.clear()

    outcome = await rig.assistant.start("Вторая", _OWNER_ID)

    assert outcome.ok is False
    # No second worktree / run for the rejected start.
    assert len(rig.worktree.created) == 1
    assert rig.runner.calls == []
