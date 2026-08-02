# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты InteractiveSessionManager — живой двусторонний claude-сеанс (BOB-083 .3).

Покрыто (safety-инварианты под тестами):
* ``open`` (owner-only): создаёт ИЗОЛИРОВАННЫЙ worktree (ветка ``bob/<slug>``, не main),
  спавнит :class:`InteractiveRunner` в валидном режиме, персистит сессию в
  ``INTERACTIVE`` и льёт вывод раннера в DM через :class:`LiveRunStreamer`;
* ``feed`` форвардит owner-реплику в stdin раннера;
* 🔴 ``stop`` — ПРЯМОЙ kill: закрывает раннер (terminate), убирает worktree и
  переводит сессию в терминальное ``CANCELLED`` (не кооперативный break);
* 🔴 одна сессия за раз: повторный ``open`` при живой сессии — отказ;
* 🔴 не-owner получает отказ (нет worktree, нет спавна);
* 🔴 менеджер НЕ открывает PR / не пушит / не мержит — commit_and_push не вызывается.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.coding import session_voice
from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.state import CodingSessionState, is_terminal
from bob.coding.usecases.interactive_session import InteractiveSessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.entities import CodingSession

_OWNER_ID = 27468732
_STRANGER_ID = 555
_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@dataclass
class _FakeInteractiveRunner:
    """Fake persistent runner: records open/feed/close; events stay live until closed."""

    canned: list[Mapping[str, object]] = field(default_factory=list)
    opened: list[tuple[str, str]] = field(default_factory=list)
    fed: list[str] = field(default_factory=list)
    close_calls: int = 0
    streamed: list[Mapping[str, object]] = field(default_factory=list)
    session_id: str | None = None  # BOB-087.D1: claude session id from the init event

    def __post_init__(self) -> None:
        self._closed = asyncio.Event()
        self.drained = asyncio.Event()  # set once every canned event has been yielded

    async def open(
        self,
        workdir: str,
        *,
        mode: str,
        resume_session_id: str | None = None,
        continue_session: bool = False,
    ) -> None:
        # BOB-087.D3: the port carries the optional resume knobs; the FRESH ``open``
        # path must never use them (asserted here — the default spawn is unchanged).
        assert resume_session_id is None
        assert continue_session is False
        self.opened.append((workdir, mode))

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def events(self) -> AsyncIterator[Mapping[str, object]]:
        for event in self.canned:
            self.streamed.append(event)
            yield event
        self.drained.set()
        await self._closed.wait()  # a real process keeps the stream open until it dies

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


@dataclass
class _FakeWorktree:
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pushes: list[tuple[str, str, str]] = field(default_factory=list)

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        slug = branch.split("/", 1)[1]
        return f"/wt/{slug}"

    async def commit_and_push(self, path: str, branch: str, message: str) -> bool:
        self.pushes.append((path, branch, message))  # must NEVER be called here
        return True

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
        return f"is-{counter['n']}"

    return _factory


@dataclass
class _Rig:
    manager: InteractiveSessionManager
    worktree: _FakeWorktree
    store: _FakeStore
    notifier: _FakeNotifier
    runner: _FakeInteractiveRunner


def _build(
    *,
    runner: _FakeInteractiveRunner | None = None,
    worktree: _FakeWorktree | None = None,
    store: _FakeStore | None = None,
    notifier: _FakeNotifier | None = None,
) -> _Rig:
    runner = runner or _FakeInteractiveRunner()
    worktree = worktree or _FakeWorktree()
    store = store or _FakeStore()
    notifier = notifier or _FakeNotifier()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=store,
        streamer_factory=lambda: _DmLiveStreamer(notifier=notifier),
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        permission_mode="acceptEdits",
    )
    return _Rig(manager, worktree, store, notifier, runner)


# --- open --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_creates_isolated_worktree_and_spawns_runner() -> None:
    rig = _build()

    outcome = await rig.manager.open("fix bug", _OWNER_ID)

    assert outcome.ok is True
    assert rig.manager.active() is True
    # Isolated worktree on a bob/<slug> branch — NEVER main (INV-2 reuse of git_worktree).
    assert rig.worktree.created == ["bob/fix-bug"]
    # Runner spawned in the isolated path under the configured permission mode.
    assert rig.runner.opened == [("/wt/fix-bug", "acceptEdits")]
    # Persisted in the live INTERACTIVE state (round-trips through the store).
    assert outcome.session is not None
    saved = rig.store.sessions[outcome.session.id]
    assert saved.state is CodingSessionState.INTERACTIVE
    assert saved.branch == "bob/fix-bug"

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_open_streams_runner_events_to_dm() -> None:
    runner = _FakeInteractiveRunner(
        canned=[
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "привет"}]}},
            {"type": "result", "subtype": "success", "result": "готово"},
        ]
    )
    rig = _build(runner=runner)

    await rig.manager.open("задача", _OWNER_ID)
    await runner.drained.wait()  # the background pump has consumed every canned event

    assert runner.streamed == runner.canned  # the live stream consumed the process output
    assert rig.notifier.sent  # rendered lines reached the owner's DM

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_non_owner_open_is_refused_no_worktree_no_spawn() -> None:
    rig = _build()

    outcome = await rig.manager.open("сделай что-нибудь", _STRANGER_ID)

    assert outcome.ok is False
    assert rig.manager.active() is False
    assert rig.worktree.created == []  # 🔴 no isolated worktree for a non-owner
    assert rig.runner.opened == []  # 🔴 no live process spawned for a non-owner
    assert rig.store.sessions == {}


# --- feed --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_forwards_owner_text_to_runner_stdin() -> None:
    rig = _build()
    await rig.manager.open("задача", _OWNER_ID)

    await rig.manager.feed("добавь тест")
    await rig.manager.feed("и запусти")

    assert rig.runner.fed == ["добавь тест", "и запусти"]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_feed_without_active_session_is_a_noop() -> None:
    rig = _build()

    await rig.manager.feed("в никуда")  # no live session — dropped, never crashes

    assert rig.runner.fed == []


# --- claude session id: persisted the MOMENT it appears (BOB-087.D5b, M5) -----


_INIT_EVENT: Mapping[str, object] = {
    "type": "system",
    "subtype": "init",
    "session_id": "claude-live-1",
}


@pytest.mark.asyncio
async def test_claude_session_id_is_persisted_as_soon_as_the_init_frame_arrives() -> None:
    # 🔴 BOB-087.D5b (M5а): id сохранялся ТОЛЬКО в ``stop``. Рестарт/краш посреди живого
    # сеанса — и id потерян навсегда, а «поднять с телефона» поднимает БОЛЕЕ СТАРУЮ нить
    # поверх свежей работы. Ассерт БЕЗ вызова stop: строка в сторе уже несёт id.
    runner = _FakeInteractiveRunner(canned=[_INIT_EVENT])
    rig = _build(runner=runner)

    opened = await rig.manager.open("задача", _OWNER_ID)
    await runner.drained.wait()
    for _ in range(10):
        await asyncio.sleep(0)

    assert opened.session is not None
    saved = rig.store.sessions[opened.session.id]
    assert saved.claude_session_id == "claude-live-1"
    assert saved.state is CodingSessionState.INTERACTIVE  # сессия ещё живая

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_a_stream_without_an_init_frame_persists_no_session_id() -> None:
    # Id не выдумывается: без init-кадра колонка остаётся None (байт-в-байт до-D1).
    runner = _FakeInteractiveRunner(
        canned=[{"type": "result", "subtype": "success", "result": "готово"}]
    )
    rig = _build(runner=runner)

    opened = await rig.manager.open("задача", _OWNER_ID)
    await runner.drained.wait()
    for _ in range(10):
        await asyncio.sleep(0)

    assert opened.session is not None
    assert rig.store.sessions[opened.session.id].claude_session_id is None

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_the_early_persisted_id_survives_a_stop_that_sees_no_runner_id() -> None:
    # ``stop`` дописывает id раннера, если тот есть; уже сохранённый id при этом не
    # затирается — цепочка «сессия за сессией» остаётся возобновляемой.
    runner = _FakeInteractiveRunner(canned=[_INIT_EVENT])
    rig = _build(runner=runner)
    opened = await rig.manager.open("задача", _OWNER_ID)
    await runner.drained.wait()
    for _ in range(10):
        await asyncio.sleep(0)

    await rig.manager.stop(_OWNER_ID)

    assert opened.session is not None
    saved = rig.store.sessions[opened.session.id]
    assert saved.claude_session_id == "claude-live-1"
    assert saved.state is CodingSessionState.CANCELLED


# --- stop: direct kill -------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_directly_kills_runner_cleans_worktree_and_is_terminal() -> None:
    rig = _build()
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.ok is True
    # 🔴 DIRECT kill: the persistent runner is closed (terminate → kill), not a break.
    assert rig.runner.close_calls == 1
    # worktree torn down (reuse of _cleanup); no live session remains.
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert rig.manager.active() is False
    # Terminal CANCELLED persisted.
    saved = rig.store.sessions[opened.session.id]
    assert saved.state is CodingSessionState.CANCELLED
    assert is_terminal(saved.state) is True


@pytest.mark.asyncio
async def test_stop_persists_the_runner_claude_session_id() -> None:
    # BOB-087.D1: the claude session id the runner captured off the init event is saved
    # onto the terminal session, so a later /code (D3) can look it up for --resume.
    rig = _build(runner=_FakeInteractiveRunner(session_id="sess-77"))
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    await rig.manager.stop(_OWNER_ID)

    saved = rig.store.sessions[opened.session.id]
    assert saved.claude_session_id == "sess-77"


@pytest.mark.asyncio
async def test_stop_without_a_captured_session_id_leaves_it_none() -> None:
    # No init id captured → the field stays None (byte-identical to a pre-D1 session).
    rig = _build()
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    await rig.manager.stop(_OWNER_ID)

    saved = rig.store.sessions[opened.session.id]
    assert saved.claude_session_id is None


@pytest.mark.asyncio
async def test_stop_without_session_is_best_effort_noop() -> None:
    rig = _build()

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.ok is False
    assert rig.runner.close_calls == 0
    assert rig.worktree.removed == []


@pytest.mark.asyncio
async def test_non_owner_stop_is_refused() -> None:
    rig = _build()
    await rig.manager.open("задача", _OWNER_ID)

    outcome = await rig.manager.stop(_STRANGER_ID)

    assert outcome.ok is False
    assert rig.runner.close_calls == 0  # 🔴 a non-owner cannot kill the owner's session
    assert rig.manager.active() is True

    await rig.manager.stop(_OWNER_ID)


# --- one session at a time ---------------------------------------------------


@pytest.mark.asyncio
async def test_second_open_is_refused_while_one_is_live() -> None:
    rig = _build()
    await rig.manager.open("first task", _OWNER_ID)

    outcome = await rig.manager.open("second task", _OWNER_ID)

    assert outcome.ok is False  # 🔴 one session at a time
    # No second worktree / spawn.
    assert rig.worktree.created == ["bob/first-task"]
    assert rig.runner.opened == [("/wt/first-task", "acceptEdits")]

    await rig.manager.stop(_OWNER_ID)


@pytest.mark.asyncio
async def test_open_again_after_stop_is_allowed() -> None:
    rig = _build()
    await rig.manager.open("first task", _OWNER_ID)
    await rig.manager.stop(_OWNER_ID)

    outcome = await rig.manager.open("second task", _OWNER_ID)

    assert outcome.ok is True
    assert rig.manager.active() is True
    assert rig.worktree.created == ["bob/first-task", "bob/second-task"]

    await rig.manager.stop(_OWNER_ID)


# --- open failure: worktree is cleaned up, no leaked session -----------------


@dataclass
class _ExplodingRunner(_FakeInteractiveRunner):
    """A runner whose spawn (``open``) fails — the manager must not leak a worktree."""

    async def open(
        self,
        workdir: str,  # noqa: ARG002
        *,
        mode: str,  # noqa: ARG002
        resume_session_id: str | None = None,  # noqa: ARG002
        continue_session: bool = False,  # noqa: ARG002
    ) -> None:
        raise RuntimeError("claude failed to spawn")


@pytest.mark.asyncio
async def test_open_spawn_failure_cleans_worktree_and_leaves_no_session() -> None:
    # 🔴 A spawn/mode fault must tear the isolated worktree back down (no orphaned
    # worktree, no live session) — the owner sees a failure, the seam stays clean.
    runner = _ExplodingRunner()
    rig = _build(runner=runner)

    outcome = await rig.manager.open("задача", _OWNER_ID)

    assert outcome.ok is False
    assert outcome.session is None
    assert rig.manager.active() is False
    # The worktree that was created for the (failed) spawn is removed again.
    assert rig.worktree.created == ["bob/zadacha"]
    assert rig.worktree.removed == ["/wt/zadacha"]
    assert rig.store.sessions == {}  # nothing persisted


@dataclass
class _CreateFailsWorktree(_FakeWorktree):
    """A worktree whose ``create`` raises — git can fail before anything is spawned."""

    async def create(self, branch: str) -> str:
        self.created.append(branch)
        raise RuntimeError("fatal: could not create worktree")


@pytest.mark.asyncio
async def test_open_worktree_failure_answers_honestly_and_claims_no_cleanup() -> None:
    # 🔴 BOB-087.D5b (B2): ``create`` жил ВНЕ try — его падение улетало из ``open`` наружу
    # и глохло выше, owner не узнавал ничего. Теперь это честный отказ; и реплика НЕ врёт
    # про уборку копии (убирать нечего — дерево не создалось).
    rig = _build(worktree=_CreateFailsWorktree())

    outcome = await rig.manager.open("задача", _OWNER_ID)

    assert outcome.ok is False
    assert outcome.session is None
    assert outcome.message == session_voice.interactive_setup_failed()
    assert "убрал" not in outcome.message.casefold()
    assert rig.manager.active() is False
    assert rig.worktree.removed == []  # нечего убирать — и Боб об уборке не заикается
    assert rig.store.sessions == {}
    assert rig.runner.opened == []


# --- stop is best-effort: a close / cleanup fault never masks the outcome -----


@dataclass
class _CloseFailsRunner(_FakeInteractiveRunner):
    """A runner whose ``close`` raises — ``stop`` must still finish terminally."""

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()
        raise RuntimeError("terminate exploded")


@pytest.mark.asyncio
async def test_stop_survives_a_runner_close_fault_and_stays_terminal() -> None:
    runner = _CloseFailsRunner()
    rig = _build(runner=runner)
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    outcome = await rig.manager.stop(_OWNER_ID)

    # Best-effort: the close fault is swallowed; the session still ends CANCELLED,
    # the worktree is still torn down, and no live session lingers (INV-4 backstop).
    assert outcome.ok is True
    assert rig.manager.active() is False
    assert rig.worktree.removed == ["/wt/zadacha"]
    saved = rig.store.sessions[opened.session.id]
    assert saved.state is CodingSessionState.CANCELLED


@dataclass
class _RemoveFailsWorktree(_FakeWorktree):
    """A worktree whose ``remove`` raises — cleanup must not mask the stop outcome."""

    async def remove(self, path: str) -> None:
        self.removed.append(path)
        raise RuntimeError("worktree removal failed")


@pytest.mark.asyncio
async def test_stop_survives_a_worktree_cleanup_fault_and_stays_terminal() -> None:
    worktree = _RemoveFailsWorktree()
    rig = _build(worktree=worktree)
    opened = await rig.manager.open("задача", _OWNER_ID)
    assert opened.session is not None

    outcome = await rig.manager.stop(_OWNER_ID)

    assert outcome.ok is True
    assert rig.manager.active() is False
    assert worktree.removed == ["/wt/zadacha"]  # remove was attempted
    saved = rig.store.sessions[opened.session.id]
    assert saved.state is CodingSessionState.CANCELLED


# --- output-stream fault is isolated (never crashes the manager) -------------


class _ExplodingStreamer:
    """A live streamer whose ``stream`` raises — the pump must isolate the fault."""

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],  # noqa: ARG002
        *,
        is_cancelled: Callable[[], bool],  # noqa: ARG002
    ) -> None:
        raise RuntimeError("output stream exploded")


@pytest.mark.asyncio
async def test_output_stream_fault_does_not_crash_the_manager() -> None:
    # An output-stream fault is fault-isolated inside the background pump: the session
    # still opens and can be stopped cleanly (the manager never crashes).
    runner = _FakeInteractiveRunner()
    worktree = _FakeWorktree()
    store = _FakeStore()
    manager = InteractiveSessionManager(
        runner_factory=lambda: runner,
        worktree=worktree,
        store=store,
        streamer_factory=_ExplodingStreamer,
        owner=_FakeOwner(),
        clock=_FakeClock(),
        id_factory=_ids(),
        permission_mode="acceptEdits",
    )

    opened = await manager.open("задача", _OWNER_ID)
    outcome = await manager.stop(_OWNER_ID)

    assert opened.ok is True
    assert outcome.ok is True
    assert manager.active() is False


# --- 🔴 never a PR / merge / push --------------------------------------------


@pytest.mark.asyncio
async def test_interactive_never_opens_pr_or_pushes_main() -> None:
    rig = _build()

    await rig.manager.open("задача", _OWNER_ID)
    await rig.manager.feed("правь")
    await rig.manager.stop(_OWNER_ID)

    # 🔴 INV-2: the interactive manager edits only inside the worktree; it NEVER
    # commits/pushes/opens a PR (the owner reviews and lands via the existing gate).
    assert rig.worktree.pushes == []
