# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""CodingAssistant feeds + flushes the distilled work journal at session end — BOB-087.B1.

Pins that the gated orchestrator (1) tees the raw execute stream through the bounded
accumulator (files touched / tests / errors — never the raw firehose) and (2) hands the
snapshot + outcome to the narrow :class:`WorkJournalRecorder` ONCE at the execute terminal
(PR_OPEN → FINISHED, no-changes → FAILED), NOT per stream-event (anti-flood, BOB-076).
🔴 Unwired (flag OFF / default) → the recorder is the null no-op: nothing is recorded, and a
raising recorder never breaks the coding path (best-effort). All on FAKE ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import CodingAssistant
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_TASK = "почини стрим"


@dataclass
class _JournalCall:
    task: str
    facts: SessionKeyFacts
    outcome: WorkOutcome
    sender_id: int | None


@dataclass
class _SpyJournal:
    calls: list[_JournalCall] = field(default_factory=list)
    raises: bool = False

    async def record_session(
        self,
        task: str,
        facts: SessionKeyFacts,
        outcome: WorkOutcome,
        *,
        sender_id: int | None = None,
    ) -> None:
        self.calls.append(_JournalCall(task, facts, outcome, sender_id))
        if self.raises:
            raise RuntimeError("journal down")


@dataclass
class _FakeRunner:
    events: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)

    async def run(
        self, workdir: str, prompt: str, *, mode: str
    ) -> AsyncIterator[Mapping[str, object]]:
        for event in self.events.get(mode, []):
            yield event


@dataclass
class _FakeWorktree:
    committed: bool = True

    async def create(self, branch: str) -> str:
        return f"/wt/{branch.split('/', 1)[1]}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        return self.committed

    async def remove(self, path: str) -> None:
        return None


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
    async def open(self, branch: str, title: str, body: str) -> str:
        return "https://github.com/x/bob/pull/7"


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
    return {"plan": [{"type": "result", "subtype": "success", "result": "план"}]}


def _execute_events() -> list[Mapping[str, object]]:
    return [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/runner.py"}},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "tests/test_x.py"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "5 passed"}]}},
        {"type": "result", "subtype": "success"},
    ]


def _assistant(*, journal: _SpyJournal | None, worktree: _FakeWorktree) -> CodingAssistant:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    return CodingAssistant(
        runner=runner,
        worktree=worktree,
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_FakeNotifier(),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        work_journal=journal,
    )


async def test_execute_success_journals_finished_with_accumulated_facts() -> None:
    journal = _SpyJournal()
    assistant = _assistant(journal=journal, worktree=_FakeWorktree())

    await assistant.start(_TASK, _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    assert len(journal.calls) == 1  # exactly once, at the terminal — not per event
    call = journal.calls[0]
    assert call.task == _TASK
    assert call.outcome is WorkOutcome.FINISHED
    assert call.sender_id == _OWNER_ID
    # The tee captured the DISTILLED substance: touched files + a passing test run.
    assert call.facts.files == ("runner.py", "test_x.py")
    assert call.facts.tests_passed is True


async def test_no_changes_journals_failed() -> None:
    journal = _SpyJournal()
    assistant = _assistant(journal=journal, worktree=_FakeWorktree(committed=False))

    await assistant.start(_TASK, _OWNER_ID)
    await assistant.approve_plan(_OWNER_ID)

    assert [c.outcome for c in journal.calls] == [WorkOutcome.FAILED]


async def test_start_and_stop_do_not_journal() -> None:
    # The journal is an execute-terminal side channel; planning/stop alone record nothing.
    journal = _SpyJournal()
    assistant = _assistant(journal=journal, worktree=_FakeWorktree())

    await assistant.start(_TASK, _OWNER_ID)
    await assistant.stop(_OWNER_ID)

    assert journal.calls == []


async def test_unwired_journal_is_noop_and_flow_unchanged() -> None:
    # No work_journal wired (flag OFF default) → the null recorder: the session still reaches
    # PR_OPEN with no error and nothing is recorded (byte-identical).
    assistant = _assistant(journal=None, worktree=_FakeWorktree())

    await assistant.start(_TASK, _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PR_OPEN


async def test_raising_journal_never_breaks_execute() -> None:
    assistant = _assistant(journal=_SpyJournal(raises=True), worktree=_FakeWorktree())

    await assistant.start(_TASK, _OWNER_ID)
    outcome = await assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PR_OPEN
