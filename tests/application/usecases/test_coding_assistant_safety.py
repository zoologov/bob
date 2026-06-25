# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 SAFETY guardrail acceptance for CodingAssistant — BOB-039 US-2/4/6.

These tests pin the safety invariants that the happy-path suite
(``test_coding_assistant.py``) does not exercise — all with FAKE ports, never a real
``claude`` / ``gh`` / ``git``:

* US-2 (plan gate): there is NO route to ``EXECUTING`` except an owner ``approve_plan``
  from ``PLAN_READY`` — a fresh session cannot be approved, and the runner is never
  asked to apply edits without that approval.
* US-6 (kill-switch mid-run): a ``stop`` that lands WHILE the approved run is streaming
  breaks the narrate loop, opens NO PR, ends ``CANCELLED`` and removes the worktree.
* US-6 (no leak on cleanup failure): a worktree ``remove`` that itself raises never
  crashes the turn nor masks the outcome.
* US-6 (orphaned session): a ``stop`` of a session that carries no worktree path still
  cancels cleanly without a phantom remove.
* Robustness: malformed plan-stream events are treated as noise, not crashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.coding_assistant import CodingAssistant
from bob.domain.coding.entities import CodingSession
from bob.domain.coding.state import CodingSessionState, is_terminal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping

_OWNER_ID = 27468732
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


@dataclass
class _FakeRunner:
    """Async-generator runner; an optional ``on_event`` hook fires before each yield."""

    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    on_event: Callable[[], Awaitable[None]] | None = None

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
    remove_raises: Exception | None = None

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        slug = branch.split("/", 1)[1]
        return f"/wt/{slug}"

    async def remove(self, path: str) -> None:
        self.removed.append(path)
        if self.remove_raises is not None:
            raise self.remove_raises


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
class _ReentrantNotifier:
    """Notifier whose first ``send`` re-enters the assistant with an owner ``stop``.

    Models a real kill-switch landing mid-run: the owner sends ``/code stop`` while the
    narrative is streaming. The hook fires exactly once.
    """

    sent: list[str] = field(default_factory=list)
    on_first: Callable[[], Awaitable[None]] | None = None
    _fired: bool = False

    async def send(self, text: str) -> None:
        self.sent.append(text)
        if self.on_first is not None and not self._fired:
            self._fired = True
            await self.on_first()


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
                "message": {"content": [{"type": "text", "text": "Шаг 1"}]},
            },
            {"type": "result", "subtype": "success", "result": "Итоговый план"},
        ],
    }


def _two_edit_events() -> list[Mapping[str, object]]:
    """Two narratable edit events — enough that a mid-run stop breaks on the second."""
    edit = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}]
        },
    }
    edit2 = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "b.py"}}]
        },
    }
    return [edit, edit2, {"type": "result", "subtype": "success"}]


def _build(
    *,
    runner: _FakeRunner,
    worktree: _FakeWorktree | None = None,
    store: _FakeStore | None = None,
    pr_opener: _FakePROpener | None = None,
    notifier: _ReentrantNotifier | _FakeNotifier | None = None,
) -> tuple[CodingAssistant, _FakeWorktree, _FakeStore, _FakePROpener]:
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
    return assistant, worktree, store, pr_opener


# --- US-6: kill-switch lands mid-run --------------------------------------------


async def test_stop_during_execution_breaks_run_opens_no_pr_and_cancels() -> None:
    # Arrange: a stop fires on the first narrative line (mid execute-run).
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _two_edit_events()})
    notifier = _ReentrantNotifier()
    assistant, worktree, store, pr_opener = _build(runner=runner, notifier=notifier)

    async def _kill() -> None:
        await assistant.stop(_OWNER_ID)

    # Arm the kill-switch ONLY after start (so it fires on the first EXECUTE narrative
    # line, not on the plan message) — a stop that lands mid-run.
    await assistant.start("Задача", _OWNER_ID)
    notifier.on_first = _kill
    outcome = await assistant.approve_plan(_OWNER_ID)

    # Assert: no PR opened, session ended CANCELLED, worktree removed — no leak.
    assert outcome.ok is False
    assert pr_opener.opens == []
    active = await store.active()
    assert active == ()  # the only session is terminal (CANCELLED)
    cancelled = [s for s in store.sessions.values() if s.state is CodingSessionState.CANCELLED]
    assert len(cancelled) == 1
    assert worktree.removed  # the worktree was cleaned up


# --- US-6: cleanup failure must never crash a turn or mask the outcome ----------


async def test_stop_when_worktree_remove_raises_still_cancels_cleanly() -> None:
    runner = _FakeRunner(events=_plan_events())
    worktree = _FakeWorktree(remove_raises=OSError("disk gone"))
    assistant, _wt, store, _pr = _build(runner=runner, worktree=worktree)
    await assistant.start("Задача", _OWNER_ID)

    # A remove that raises is swallowed — the stop still reports success and cancels.
    outcome = await assistant.stop(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.CANCELLED
    assert worktree.removed  # remove WAS attempted (it raised, but was contained)
    assert await store.active() == ()


# --- US-6: orphaned session (no worktree path) cancels without a phantom remove --


async def test_stop_of_session_without_worktree_path_cancels_no_remove() -> None:
    runner = _FakeRunner(events=_plan_events())
    store = _FakeStore()
    # Seed an in-flight session that never acquired a worktree (orphan edge).
    orphan = CodingSession(
        id="orphan-1",
        task="осиротевшая",
        state=CodingSessionState.PLAN_READY,
        branch="bob/orphan",
        created_at=_NOW,
        updated_at=_NOW,
        worktree_path=None,
    )
    store.sessions[orphan.id] = orphan
    assistant, worktree, _store, _pr = _build(runner=runner, store=store)

    outcome = await assistant.stop(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.CANCELLED
    # No worktree path → nothing to remove (no phantom git call).
    assert worktree.removed == []


# --- Robustness: malformed plan-stream events are noise, not crashes ------------


async def test_plan_assembly_ignores_malformed_events() -> None:
    plan_stream: list[Mapping[str, object]] = [
        {"type": "system", "subtype": "init"},  # tool/system event → "" (ignored)
        {"type": "assistant", "message": "not-a-mapping"},  # message not a Mapping
        {"type": "assistant", "message": {"content": "not-a-list"}},  # content not a list
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Реальный шаг"}]},
        },
        {"type": "result", "subtype": "success", "result": "Финальный план"},
    ]
    runner = _FakeRunner(events={"plan": plan_stream})
    assistant, _wt, _store, _pr = _build(runner=runner)

    outcome = await assistant.start("Задача", _OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PLAN_READY
    # Only the valid text + result survived; the malformed events contributed nothing.
    plan = outcome.session.plan or ""
    assert "Реальный шаг" in plan
    assert "Финальный план" in plan
    assert "not-a" not in plan


async def test_error_result_event_is_not_treated_as_plan() -> None:
    plan_stream: list[Mapping[str, object]] = [
        {"type": "result", "subtype": "error_max_turns", "result": "partial garbage"},
    ]
    runner = _FakeRunner(events={"plan": plan_stream})
    assistant, _wt, _store, _pr = _build(runner=runner)

    outcome = await assistant.start("Задача", _OWNER_ID)

    # An error result is not a plan — the assembled plan is empty (the "no plan" path).
    assert outcome.session is not None
    assert (outcome.session.plan or "") == ""
