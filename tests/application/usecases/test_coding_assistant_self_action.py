# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Автобиография coding-сессии — CodingAssistant пишет self_action на переходах (BOB-079.2).

Пинует, что гейтед оркестратор оседает поступки Боба от первого лица через узкий
:class:`~bob.memory.ports.SelfActionRecorder` на каждом lifecycle-переходе:

* ``start`` → ``CODING_STARTED``; ``stop`` → ``CODING_ABORTED``;
* успех (PR открыт) → ``CODING_FINISHED``; провал/нет-изменений → ``CODING_FAILED``;
* runaway (кап нарратива BOB-076 сработал) → ``CODING_RUNAWAY`` ровно один раз за прогон;
* 🔴 best-effort: бросающий recorder не роняет coding-путь (урок Part D BOB-078).

Всё на FAKE-портах (spy-recorder), без реального ``claude``/``gh``/``git``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.coding_assistant import _MAX_NARRATION, CodingAssistant
from bob.memory.self_action import SelfAction, SelfActionKind
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


@dataclass
class _RecordCall:
    """One captured recorder invocation (the poured self-action + provenance)."""

    action: SelfAction
    sender_id: int | None
    visibility: str | None


@dataclass
class _SpyRecorder:
    """Spy :class:`SelfActionRecorder`: captures every call; may be told to raise."""

    calls: list[_RecordCall] = field(default_factory=list)
    raises: bool = False

    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        self.calls.append(_RecordCall(action, sender_id, visibility))
        if self.raises:
            raise RuntimeError("recorder is down")

    def kinds(self) -> list[SelfActionKind]:
        return [call.action.kind for call in self.calls]


@dataclass
class _FakeRunner:
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
    pushes: list[tuple[str, str, str]] = field(default_factory=list)
    committed: bool = True

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        slug = branch.split("/", 1)[1]
        return f"/wt/{slug}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))
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


def _edit_event(path: str) -> Mapping[str, object]:
    return {"type": "tool_use", "name": "Edit", "input": {"file_path": path}}


def _execute_events(edits: int = 1) -> list[Mapping[str, object]]:
    events: list[Mapping[str, object]] = [_edit_event(f"f{i}.py") for i in range(edits)]
    events.append({"type": "result", "subtype": "success"})
    return events


_TASK = "Добавить ручку health"


@dataclass
class _Rig:
    assistant: CodingAssistant
    recorder: _SpyRecorder
    worktree: _FakeWorktree
    store: _FakeStore
    runner: _FakeRunner
    notifier: _FakeNotifier


def _build(
    *,
    recorder: _SpyRecorder | None = None,
    runner: _FakeRunner | None = None,
    worktree: _FakeWorktree | None = None,
) -> _Rig:
    recorder = recorder or _SpyRecorder()
    runner = runner or _FakeRunner(events=_plan_events())
    worktree = worktree or _FakeWorktree()
    store = _FakeStore()
    notifier = _FakeNotifier()
    assistant = CodingAssistant(
        runner=runner,
        worktree=worktree,
        store=store,
        pr_opener=_FakePROpener(),
        notifier=notifier,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        recorder=recorder,
    )
    return _Rig(assistant, recorder, worktree, store, runner, notifier)


async def _to_plan_ready(rig: _Rig) -> None:
    await rig.assistant.start(_TASK, _OWNER_ID)


@pytest.mark.asyncio
async def test_start_records_coding_started_first_person_owner_private() -> None:
    rig = _build()

    await rig.assistant.start(_TASK, _OWNER_ID)

    started = [c for c in rig.recorder.calls if c.action.kind is SelfActionKind.CODING_STARTED]
    assert len(started) == 1
    call = started[0]
    assert call.action.target == _TASK
    assert call.sender_id == _OWNER_ID
    assert call.visibility == VISIBILITY_OWNER_PRIVATE


@pytest.mark.asyncio
async def test_stop_records_coding_aborted() -> None:
    rig = _build()
    await _to_plan_ready(rig)

    await rig.assistant.stop(_OWNER_ID)

    assert SelfActionKind.CODING_ABORTED in rig.recorder.kinds()
    aborted = next(c for c in rig.recorder.calls if c.action.kind is SelfActionKind.CODING_ABORTED)
    assert aborted.action.target == _TASK
    assert aborted.sender_id == _OWNER_ID


@pytest.mark.asyncio
async def test_execute_success_records_coding_finished() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    rig = _build(runner=runner)
    await _to_plan_ready(rig)

    await rig.assistant.approve_plan(_OWNER_ID)

    assert SelfActionKind.CODING_FINISHED in rig.recorder.kinds()
    finished = next(
        c for c in rig.recorder.calls if c.action.kind is SelfActionKind.CODING_FINISHED
    )
    assert finished.action.target == _TASK
    assert finished.sender_id == _OWNER_ID


@pytest.mark.asyncio
async def test_execute_no_changes_records_coding_failed() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    worktree = _FakeWorktree(committed=False)  # claude changed nothing → FAILED, no PR
    rig = _build(runner=runner, worktree=worktree)
    await _to_plan_ready(rig)

    await rig.assistant.approve_plan(_OWNER_ID)

    assert SelfActionKind.CODING_FAILED in rig.recorder.kinds()


@pytest.mark.asyncio
async def test_plan_run_fault_records_coding_failed_with_detail() -> None:
    runner = _FakeRunner(errors={"plan": RuntimeError("claude exploded")})
    rig = _build(runner=runner)

    await rig.assistant.start(_TASK, _OWNER_ID)

    failed = [c for c in rig.recorder.calls if c.action.kind is SelfActionKind.CODING_FAILED]
    assert len(failed) == 1
    assert failed[0].action.target == _TASK
    assert failed[0].action.detail is not None
    assert "claude exploded" in failed[0].action.detail


@pytest.mark.asyncio
async def test_runaway_records_coding_runaway_exactly_once() -> None:
    # More narratable edits than the cap → the flood-cap trips; the autobiographical
    # trace of the runaway must be recorded EXACTLY ONCE (per run, not per line).
    runner = _FakeRunner(
        events={**_plan_events(), "acceptEdits": _execute_events(edits=_MAX_NARRATION + 5)}
    )
    rig = _build(runner=runner)
    await _to_plan_ready(rig)

    await rig.assistant.approve_plan(_OWNER_ID)

    runaway = [c for c in rig.recorder.calls if c.action.kind is SelfActionKind.CODING_RUNAWAY]
    assert len(runaway) == 1
    assert runaway[0].action.target == _TASK


@pytest.mark.asyncio
async def test_no_runaway_when_cap_not_hit() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events(edits=2)})
    rig = _build(runner=runner)
    await _to_plan_ready(rig)

    await rig.assistant.approve_plan(_OWNER_ID)

    assert SelfActionKind.CODING_RUNAWAY not in rig.recorder.kinds()


@pytest.mark.asyncio
async def test_raising_recorder_never_breaks_start() -> None:
    rig = _build(recorder=_SpyRecorder(raises=True))

    outcome = await rig.assistant.start(_TASK, _OWNER_ID)

    assert outcome.ok is True  # session reached PLAN_READY despite the recorder fault
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PLAN_READY


@pytest.mark.asyncio
async def test_raising_recorder_never_breaks_stop() -> None:
    rig = _build(recorder=_SpyRecorder(raises=True))
    await _to_plan_ready(rig)

    outcome = await rig.assistant.stop(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.CANCELLED


@pytest.mark.asyncio
async def test_raising_recorder_never_breaks_execute() -> None:
    runner = _FakeRunner(events={**_plan_events(), "acceptEdits": _execute_events()})
    rig = _build(recorder=_SpyRecorder(raises=True), runner=runner)
    await _to_plan_ready(rig)

    outcome = await rig.assistant.approve_plan(_OWNER_ID)

    assert outcome.ok is True
    assert outcome.session is not None
    assert outcome.session.state is CodingSessionState.PR_OPEN


@pytest.mark.asyncio
async def test_default_recorder_is_noop_and_flow_unchanged() -> None:
    # No recorder wired → the assistant still plans/stops with no error (byte-identical).
    assistant = CodingAssistant(
        runner=_FakeRunner(events=_plan_events()),
        worktree=_FakeWorktree(),
        store=_FakeStore(),
        pr_opener=_FakePROpener(),
        notifier=_FakeNotifier(),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
    )

    outcome = await assistant.start(_TASK, _OWNER_ID)

    assert outcome.ok is True
