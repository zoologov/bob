# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for PursueGoalsTick — Bob's self-directed pursuit of his OWN goals (BOB-015 .3).

The most safety-critical wave: the tick advances a goal autonomously, so the
guardrails are pinned hard on fakes here (the full coverage is .4). These tests
exercise the strict gate order and the autonomy invariants:

* kill-switch set → the tick does NOTHING (no load, no dispatch, no message);
* governance veto (quiet-hours / owner-mute) → NOTHING;
* the happy path: gate open → next_safe_task → safe capability dispatched →
  task DONE → episode written → owner told (transparency);
* an external-agency-only graph is NEVER executed — it is OFFERED to the owner;
* an unapproved (PROPOSED) goal is unreachable (next_safe_task excludes it);
* the safe-allowlist is the hard boundary: a capability off the allowlist is never
  dispatched (SafeCapabilityDispatcher), so the autonomous path cannot escalate;
* completing the last task moves the goal ACTIVE → DONE;
* the per-window task ceiling (rate-limit) stops a second advance.
"""

from __future__ import annotations

import random
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.capabilities.usecases.registry import (
    CapabilityRegistry,
    SafeCapabilityDispatcher,
)
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.state import PersonalityState
from bob.personality.taste import TasteEngine
from bob.proactivity.goals.entities import Goal, GoalOrigin, Task
from bob.proactivity.goals.graph import GoalGraph
from bob.proactivity.goals.state import GoalState, TaskState
from bob.proactivity.governance import Governance, GovernanceConfig
from bob.proactivity.social_energy import SocialEnergy
from bob.proactivity.state import ProactivityState
from bob.proactivity.usecases.pursue_goals import PursueGoalsTick

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.capabilities.ports import Permission

PERSONA = "bob"
CHAT_ID = 42
# A weekday mid-morning instant: outside the default 23:00–09:00 quiet hours so
# governance permits, with no markers in history (no cooldown / min-gap veto).
NOW = datetime(2026, 6, 24, 11, 0, tzinfo=UTC)


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeGoalStore:
    """In-memory GoalStore: holds a graph, records the atomic state moves."""

    def __init__(self, graph: GoalGraph) -> None:
        self._graph = graph
        self.task_moves: list[tuple[str, TaskState]] = []
        self.goal_moves: list[tuple[str, GoalState]] = []

    async def load(self, persona_id: str) -> GoalGraph:
        return self._graph

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:
        self.task_moves.append((task_id, state))
        self._graph = GoalGraph(
            goals=self._graph.goals,
            tasks=tuple(
                _with_state(t, state) if t.id == task_id else t
                for t in self._graph.tasks
            ),
        )

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None:
        self.goal_moves.append((goal_id, state))


class _FakePursuitStore:
    def __init__(self, *, stopped: bool) -> None:
        self._stopped = stopped
        self.checked = False

    async def is_pursuit_stopped(self, persona_id: str) -> bool:
        self.checked = True
        return self._stopped


class _FakeHistory:
    def __init__(self, state: ProactivityState) -> None:
        self._state = state

    async def load(self, persona_id: str) -> ProactivityState:
        return self._state


class _FakeWindow:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    async def progress_count_in_window(self, *, now: datetime) -> int:
        return self._count


class _RecordingEpisodes:
    def __init__(self) -> None:
        self.saved: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.saved.append(episode)


class _CapturingGateway:
    def __init__(self) -> None:
        self.messages: list[str] = []

    @asynccontextmanager
    async def typing_indicator(self, *, chat_id: int) -> AsyncIterator[None]:
        yield

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.messages.append(markdown)

    async def send_photo(
        self, *, chat_id: int, photo: bytes, caption: str | None = None
    ) -> None:
        # BOB-035: ReplyGateway parity; the goal tick never posts a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> None:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

class _SafeCapability:
    """A trivial safe capability that records its dispatched args."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls: list[Mapping[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "a safe step"

    @property
    def input_schema(self) -> Mapping[str, object]:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    @property
    def permission(self) -> Permission:
        return "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        return "done"


def _with_state(task: Task, state: TaskState) -> Task:
    return Task(
        id=task.id,
        goal_id=task.goal_id,
        summary=task.summary,
        deps=task.deps,
        state=state,
        needs_external_agency=task.needs_external_agency,
    )


def _goal(goal_id: str, *, state: GoalState, origin: GoalOrigin = GoalOrigin.OWNER) -> Goal:
    return Goal(
        id=goal_id,
        title=f"цель {goal_id}",
        description="описание",
        priority=1,
        criteria="критерий",
        state=state,
        created_at=NOW,
        origin=origin,
    )


def _task(
    task_id: str,
    goal_id: str,
    *,
    state: TaskState = TaskState.READY,
    deps: tuple[str, ...] = (),
    external: bool = False,
) -> Task:
    return Task(
        id=task_id,
        goal_id=goal_id,
        summary=f"задача {task_id}",
        deps=deps,
        state=state,
        needs_external_agency=external,
    )


def _enabled_state() -> ProactivityState:
    return ProactivityState(
        social_energy=SocialEnergy(0.0),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=True,
    )


_Built = tuple[
    PursueGoalsTick,
    "_FakeGoalStore",
    "_RecordingEpisodes",
    "_CapturingGateway",
    "dict[str, _SafeCapability]",
]


def _build_tick(
    *,
    graph: GoalGraph,
    stopped: bool = False,
    state: ProactivityState | None = None,
    window: int = 0,
    safe_capabilities: tuple[str, ...] = ("note_capability",),
    registered: tuple[str, ...] = ("note_capability",),
    governance: Governance | None = None,
    max_tasks_per_window: int = 1,
    now: datetime = NOW,
) -> _Built:
    goal_store = _FakeGoalStore(graph)
    episodes = _RecordingEpisodes()
    gateway = _CapturingGateway()
    registry = CapabilityRegistry()
    caps = {name: _SafeCapability(name) for name in registered}
    for cap in caps.values():
        registry.register(cap)
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=safe_capabilities)
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=goal_store,
        pursuit_store=_FakePursuitStore(stopped=stopped),
        governance=governance if governance is not None else Governance(),
        history=_FakeHistory(state if state is not None else _enabled_state()),
        window=_FakeWindow(window),
        dispatcher=dispatcher,
        episodes=episodes,
        gateway=gateway,
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(now),
        rng=random.Random(7),
        safe_capabilities=safe_capabilities,
        max_tasks_per_window=max_tasks_per_window,
    )
    return tick, goal_store, episodes, gateway, caps


def _soul() -> SOUL:
    neutral = Mood()
    return SOUL(identity="Bob", mood=neutral, mood_baseline=neutral, taste=TasteEngine())


# --- gate order ---------------------------------------------------------------


async def test_kill_switch_stops_everything() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph, stopped=True)

    await tick.run()

    assert store.task_moves == []
    assert episodes.saved == []
    assert gateway.messages == []
    assert caps["note_capability"].calls == []


async def test_governance_veto_does_nothing() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    muted = ProactivityState(
        social_energy=SocialEnergy(0.0),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=False,  # owner-mute → governance veto
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph, state=muted)

    await tick.run()

    assert store.task_moves == []
    assert gateway.messages == []
    assert caps["note_capability"].calls == []


async def test_quiet_hours_veto_does_nothing() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    # 02:00 falls inside the default 23:00–09:00 quiet window.
    night = datetime(2026, 6, 24, 2, 0, tzinfo=UTC)
    tick, store, episodes, gateway, caps = _build_tick(graph=graph, now=night)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []


# --- happy path ---------------------------------------------------------------


async def test_advances_one_safe_task_and_tells_owner() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    # READY → IN_PROGRESS → DONE.
    assert (("t1", TaskState.IN_PROGRESS) in store.task_moves)
    assert (("t1", TaskState.DONE) in store.task_moves)
    # The safe capability ran with the task summary as the query.
    assert caps["note_capability"].calls == [{"query": "задача t1"}]
    # Transparency: an episode AND an owner progress message.
    assert len(episodes.saved) == 1
    assert episodes.saved[0]["event_type"] == "goal_progress"
    assert len(gateway.messages) == 1
    assert "цель g1" in gateway.messages[0]


async def test_completing_last_task_marks_goal_done() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert ("g1", GoalState.DONE) in store.goal_moves


# --- autonomy invariants ------------------------------------------------------


async def test_external_agency_task_is_offered_not_executed() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1", external=True),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    # NEVER executed: no state move, no dispatch, no episode.
    assert store.task_moves == []
    assert caps["note_capability"].calls == []
    assert episodes.saved == []
    # OFFERED to the owner instead (stage-C proposal).
    assert len(gateway.messages) == 1
    assert "стадия C" in gateway.messages[0]


async def test_unapproved_goal_is_unreachable() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.PROPOSED, origin=GoalOrigin.BOB_PROPOSED),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []
    assert gateway.messages == []


async def test_paused_goal_is_unreachable() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.PAUSED),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []


async def test_capability_off_allowlist_is_never_dispatched_task_blocked() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    # The registry holds an external capability, but it is NOT on the allowlist:
    # the safe dispatcher hides it, so the autonomous path cannot run it.
    tick, store, episodes, gateway, caps = _build_tick(
        graph=graph,
        registered=("external_tool",),
        safe_capabilities=("note_capability",),  # not registered → nothing runnable
    )

    await tick.run()

    assert caps["external_tool"].calls == []
    # No safe step found → the task is BLOCKED (visible), not silently DONE.
    assert ("t1", TaskState.BLOCKED) in store.task_moves
    assert ("t1", TaskState.DONE) not in store.task_moves
    assert episodes.saved == []


async def test_empty_allowlist_runs_nothing() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, episodes, gateway, caps = _build_tick(
        graph=graph,
        safe_capabilities=(),
        registered=("note_capability",),
    )

    await tick.run()

    assert caps["note_capability"].calls == []
    assert ("t1", TaskState.BLOCKED) in store.task_moves


# --- rate-limit ---------------------------------------------------------------


async def test_per_window_ceiling_blocks_advance() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    # Already at the ceiling for the window → no advance this tick.
    tick, store, episodes, gateway, caps = _build_tick(
        graph=graph, window=1, max_tasks_per_window=1
    )

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []
    assert episodes.saved == []


# --- dispatcher unit ----------------------------------------------------------


async def test_safe_dispatcher_refuses_off_allowlist() -> None:
    registry = CapabilityRegistry()
    registry.register(_SafeCapability("external_tool"))
    registry.register(_SafeCapability("note_capability"))
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("note_capability",))

    # Allow-listed → reachable; off the allowlist → hidden even though registered.
    assert dispatcher.allows("note_capability") is True
    assert dispatcher.allows("external_tool") is False

    import pytest

    from bob.capabilities.usecases.registry import CapabilityNotAllowedError

    with pytest.raises(CapabilityNotAllowedError):
        await dispatcher.dispatch("external_tool", {})
    # The allow-listed one runs straight through.
    assert await dispatcher.dispatch("note_capability", {"query": "x"}) == "done"


def test_governance_config_is_the_proactive_machine() -> None:
    # Sanity: the tick reuses the SAME Governance type the proactive chat uses, so
    # one config governs both reach-out paths.
    gov = Governance(config=GovernanceConfig(max_per_window=2))
    assert isinstance(gov, Governance)


# --- gate ORDER (the safety-critical invariant: gates fire BEFORE any work) ----


class _SpyGoalStore(_FakeGoalStore):
    """A goal store that records whether ``load`` was ever consulted."""

    def __init__(self, graph: GoalGraph) -> None:
        super().__init__(graph)
        self.load_calls = 0

    async def load(self, persona_id: str) -> GoalGraph:
        self.load_calls += 1
        return await super().load(persona_id)


def _build_with_spy_store(
    *,
    graph: GoalGraph,
    stopped: bool = False,
    state: ProactivityState | None = None,
    now: datetime = NOW,
) -> tuple[PursueGoalsTick, _SpyGoalStore, _CapturingGateway]:
    spy = _SpyGoalStore(graph)
    episodes = _RecordingEpisodes()
    gateway = _CapturingGateway()
    registry = CapabilityRegistry()
    cap = _SafeCapability("note_capability")
    registry.register(cap)
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("note_capability",))
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=spy,
        pursuit_store=_FakePursuitStore(stopped=stopped),
        governance=Governance(),
        history=_FakeHistory(state if state is not None else _enabled_state()),
        window=_FakeWindow(0),
        dispatcher=dispatcher,
        episodes=episodes,
        gateway=gateway,
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(now),
        rng=random.Random(7),
        safe_capabilities=("note_capability",),
        max_tasks_per_window=1,
    )
    return tick, spy, gateway


async def test_kill_switch_short_circuits_before_loading_the_graph() -> None:
    # Authz-before-autonomy ordering: a set kill-switch ends the tick BEFORE the
    # goal store is even consulted — zero work, not "work then discard".
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, spy, gateway = _build_with_spy_store(graph=graph, stopped=True)

    await tick.run()

    assert spy.load_calls == 0
    assert spy.task_moves == []
    assert gateway.messages == []


async def test_governance_veto_short_circuits_before_loading_the_graph() -> None:
    # A governance veto (owner-mute here) also ends the tick before any goal load.
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    muted = ProactivityState(
        social_energy=SocialEnergy(0.0),
        last_spoke_at=None,
        last_user_msg_at=None,
        proactivity_enabled=False,
    )
    tick, spy, _ = _build_with_spy_store(graph=graph, state=muted)

    await tick.run()

    assert spy.load_calls == 0
    assert spy.task_moves == []


async def test_kill_switch_is_checked_before_governance_history() -> None:
    # Strict order: the kill-switch read happens, the governance history read does
    # NOT (the tick exits at the kill-switch before building the history snapshot).
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )

    class _CountingHistory:
        def __init__(self, state: ProactivityState) -> None:
            self._state = state
            self.loads = 0

        async def load(self, persona_id: str) -> ProactivityState:
            self.loads += 1
            return self._state

    history = _CountingHistory(_enabled_state())
    pursuit = _FakePursuitStore(stopped=True)
    registry = CapabilityRegistry()
    registry.register(_SafeCapability("note_capability"))
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("note_capability",))
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=_FakeGoalStore(graph),
        pursuit_store=pursuit,
        governance=Governance(),
        history=history,
        window=_FakeWindow(0),
        dispatcher=dispatcher,
        episodes=_RecordingEpisodes(),
        gateway=_CapturingGateway(),
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(NOW),
        rng=random.Random(7),
        safe_capabilities=("note_capability",),
    )

    await tick.run()

    assert pursuit.checked is True
    assert history.loads == 0  # never reached — kill-switch came first


# --- authz-before-autonomy matrix: only APPROVED/ACTIVE goals are touched ------


async def test_tick_advances_only_approved_and_active_goals_in_a_mixed_graph() -> None:
    # A graph with a goal in EVERY state, each with one ready safe task. The tick
    # must pick a task from an APPROVED/ACTIVE goal and never from the others.
    states = [
        GoalState.PROPOSED,
        GoalState.APPROVED,
        GoalState.ACTIVE,
        GoalState.BLOCKED,
        GoalState.PAUSED,
        GoalState.DONE,
        GoalState.CANCELLED,
    ]
    goals = tuple(_goal(f"g_{s.value}", state=s) for s in states)
    tasks = tuple(_task(f"t_{s.value}", f"g_{s.value}") for s in states)
    graph = GoalGraph(goals=goals, tasks=tasks)
    tick, store, _episodes, _gateway, _caps = _build_tick(graph=graph)

    await tick.run()

    advanced = {task_id for task_id, _state in store.task_moves}
    pursuable = {"t_approved", "t_active"}
    # Exactly the pursuable goals' tasks may move; nothing from PROPOSED/BLOCKED/
    # PAUSED/DONE/CANCELLED ever does (one task advances per tick).
    assert advanced <= pursuable
    assert advanced  # something DID advance (the gate is not over-eager)


async def test_blocked_goal_is_unreachable() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.BLOCKED),),
        tasks=(_task("t1", "g1"),),
    )
    tick, store, _episodes, _gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []


async def test_cancelled_and_done_goals_are_unreachable() -> None:
    graph = GoalGraph(
        goals=(
            _goal("g_done", state=GoalState.DONE),
            _goal("g_cancelled", state=GoalState.CANCELLED),
        ),
        tasks=(_task("t1", "g_done"), _task("t2", "g_cancelled")),
    )
    tick, store, _episodes, _gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []


# --- dispatch failure is contained (BLOCKED, never an escalation) -------------


async def test_dispatch_failure_blocks_task_without_escalating() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )

    class _BoomCapability(_SafeCapability):
        async def execute(self, args: Mapping[str, object]) -> object:
            raise RuntimeError("capability blew up")

    goal_store = _FakeGoalStore(graph)
    episodes = _RecordingEpisodes()
    gateway = _CapturingGateway()
    registry = CapabilityRegistry()
    registry.register(_BoomCapability("note_capability"))
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("note_capability",))
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=goal_store,
        pursuit_store=_FakePursuitStore(stopped=False),
        governance=Governance(),
        history=_FakeHistory(_enabled_state()),
        window=_FakeWindow(0),
        dispatcher=dispatcher,
        episodes=episodes,
        gateway=gateway,
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(NOW),
        rng=random.Random(7),
        safe_capabilities=("note_capability",),
    )

    await tick.run()

    # A failed safe step BLOCKS the task — it is never marked DONE, no episode, no
    # owner message (a stuck step is visible, not a silent success/escalation).
    assert ("t1", TaskState.BLOCKED) in goal_store.task_moves
    assert ("t1", TaskState.DONE) not in goal_store.task_moves
    assert episodes.saved == []
    assert gateway.messages == []


# --- external proposal even when a graph mixes safe + external tasks ----------


async def test_external_task_offered_when_no_safe_task_remains() -> None:
    # The only ready task needs external agency; there is no safe task → the tick
    # OFFERS the stage-C gate (proposal), it never executes anything.
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.APPROVED),),
        tasks=(_task("ext", "g1", external=True),),
    )
    tick, store, episodes, gateway, caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert caps["note_capability"].calls == []
    assert episodes.saved == []
    assert len(gateway.messages) == 1
    assert "стадия C" in gateway.messages[0]


async def test_no_proposal_when_external_task_not_yet_ready() -> None:
    # An external task gated behind an unfinished dep is NOT yet a proposal — the
    # tick stays completely silent (nothing ready, nothing to offer).
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(
            _task("a", "g1", state=TaskState.IN_PROGRESS),
            _task("ext", "g1", deps=("a",), external=True),
        ),
    )
    tick, store, episodes, gateway, _caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert episodes.saved == []
    assert gateway.messages == []


# --- transparency: the episode carries the goal/task trail --------------------


async def test_progress_episode_records_goal_and_task_content() -> None:
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    tick, _store, episodes, gateway, _caps = _build_tick(graph=graph)

    await tick.run()

    assert len(episodes.saved) == 1
    episode = episodes.saved[0]
    assert episode["event_type"] == "goal_progress"
    # The episode is a recallable trail: it names the goal and the task advanced.
    assert "цель g1" in str(episode["content"])
    assert "задача t1" in str(episode["content"])
    assert "goal" in str(episode["tags"])
    # And the owner is told in the same cycle (episode + message together).
    assert len(gateway.messages) == 1


# --- conservative defaults (pursuit is OFF/inert until explicitly wired) -------


def test_safe_capabilities_default_to_empty_allowlist() -> None:
    # The tick's default safe-allowlist is empty: with no capabilities wired,
    # nothing is runnable autonomously (the conservative default).
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=_FakeGoalStore(GoalGraph(goals=(), tasks=())),
        pursuit_store=_FakePursuitStore(stopped=False),
        governance=Governance(),
        history=_FakeHistory(_enabled_state()),
        window=_FakeWindow(0),
        dispatcher=SafeCapabilityDispatcher(CapabilityRegistry(), allowlist=()),
        episodes=_RecordingEpisodes(),
        gateway=_CapturingGateway(),
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(NOW),
        rng=random.Random(7),
    )

    assert tick._safe_capabilities == ()
    assert tick._max_tasks_per_window == 1


async def test_skips_preference_name_not_allowed_then_runs_an_allowed_one() -> None:
    # safe_capabilities (the preference order) lists a name the dispatcher does NOT
    # allow, FOLLOWED by one it does. The tick skips the disallowed preference and
    # runs the allowed capability — the dispatcher allowlist is the hard boundary,
    # the preference order is only a hint among what is already safe.
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(_task("t1", "g1"),),
    )
    note = _SafeCapability("note_capability")
    registry = CapabilityRegistry()
    registry.register(note)
    # Dispatcher allows ONLY note_capability; the preference also lists ghost_pref.
    dispatcher = SafeCapabilityDispatcher(registry, allowlist=("note_capability",))
    goal_store = _FakeGoalStore(graph)
    tick = PursueGoalsTick(
        persona_id=PERSONA,
        chat_id=CHAT_ID,
        goal_store=goal_store,
        pursuit_store=_FakePursuitStore(stopped=False),
        governance=Governance(),
        history=_FakeHistory(_enabled_state()),
        window=_FakeWindow(0),
        dispatcher=dispatcher,
        episodes=_RecordingEpisodes(),
        gateway=_CapturingGateway(),
        personality=PersonalityState(soul=_soul()),
        clock=_FixedClock(NOW),
        rng=random.Random(0),
        safe_capabilities=("ghost_pref", "note_capability"),
    )

    await tick.run()

    # ghost_pref was skipped (dispatcher disallows it); note_capability ran.
    assert note.calls == [{"query": "задача t1"}]
    assert ("t1", TaskState.DONE) in goal_store.task_moves


async def test_goal_with_remaining_tasks_is_not_completed() -> None:
    # Advancing one task of a two-task goal does NOT complete the goal (the other
    # task is still NEW) — is_goal_complete stays False, no ACTIVE→DONE move.
    graph = GoalGraph(
        goals=(_goal("g1", state=GoalState.ACTIVE),),
        tasks=(
            _task("t1", "g1"),
            _task("t2", "g1", state=TaskState.NEW),
        ),
    )
    tick, store, _episodes, _gateway, _caps = _build_tick(graph=graph)

    await tick.run()

    # One task advanced to DONE, but the goal is NOT marked DONE (t2 outstanding).
    assert any(state is TaskState.DONE for _tid, state in store.task_moves)
    assert ("g1", GoalState.DONE) not in store.goal_moves


async def test_empty_graph_is_a_silent_no_op() -> None:
    # No goals at all → the tick loads, finds nothing, and does nothing (no crash,
    # no message). The everyday steady state when Bob has no approved goals.
    graph = GoalGraph(goals=(), tasks=())
    tick, store, episodes, gateway, _caps = _build_tick(graph=graph)

    await tick.run()

    assert store.task_moves == []
    assert store.goal_moves == []
    assert episodes.saved == []
    assert gateway.messages == []
