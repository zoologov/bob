# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Proactivity ports — the drive engine, goals, planning, and self-improvement.

The proactivity-state store (:class:`ProactivityStore`), the goal graph store
(:class:`GoalStore`) and its planner seam (:class:`Planner`, BOB-015), plus the
self-improvement rule store (:class:`SelfImprovementStore`) and its metacognitive
detector (:class:`PatternDetector`, BOB-028). These are *interfaces only*: structural
:class:`typing.Protocol` definitions with no implementations; the SQLite-backed
adapters (and LLM-backed planner/detector) live in ``bob.infrastructure``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.proactivity.goals.entities import Goal, Task
    from bob.proactivity.goals.graph import GoalGraph
    from bob.proactivity.goals.state import GoalState, TaskState
    from bob.proactivity.self_improvement import (
        ImprovementRule,
        ImprovementSignals,
        RuleState,
    )
    from bob.proactivity.state import ProactivityState


@runtime_checkable
class Planner(Protocol):
    """Decompose a goal into executable tasks (the Planner seam, BOB-015 .2).

    Given an APPROVED :class:`~bob.proactivity.goals.entities.Goal`, an implementation
    asks an LLM (Tier-1 reasoning) to break it into atomic
    :class:`~bob.proactivity.goals.entities.Task` units — each carrying its ``deps``
    (predecessor task ids, same goal) and the ``needs_external_agency`` flag
    classifying whether it requires stage-C (code / external tools / filesystem /
    external APIs). Returned tasks are fresh, in :class:`TaskState.NEW`. The
    contract is deliberately abstract: the live realisation parses strict JSON from
    a reasoning model (markdown-fenced / preamble-tolerant, like fact extraction),
    and a deterministic fake decomposes in tests with no network.
    """

    async def decompose(self, goal: Goal) -> Sequence[Task]:
        """Return the tasks ``goal`` decomposes into (in :class:`TaskState.NEW`)."""
        ...


@runtime_checkable
class PatternDetector(Protocol):
    """Formulate candidate rules from signals about Bob's own behaviour (BOB-028 .2).

    The metacognitive detector: given :class:`ImprovementSignals` (a slice of Bob's
    self-observations — self-repeats, addressivity outcomes, verbosity misses,
    relationship deltas, a stuck mood, owner friction, what landed) it returns
    candidate :class:`~bob.proactivity.self_improvement.ImprovementRule`
    objects — EACH strictly in ``state=PROPOSED`` and ``origin=BOB_PROPOSED`` (the
    detector only PROPOSES; only the owner approval of the .3 use-case moves a rule to
    APPROVED), with ``lever`` taken ONLY from the hard
    :class:`~bob.proactivity.self_improvement.Lever` allowlist and ``magnitude``
    in ``[0, 1]`` (application .3 clamps it again).

    The contract is abstract on purpose: the live realisation asks an LLM and parses
    strict JSON as tolerantly as fact extraction (markdown-fenced / preamble / trailing
    garbage tolerated; malformed output -> an empty sequence, never a raise), while a
    deterministic fake proposes in tests with no network. No I/O in the contract.
    """

    async def detect(self, signals: ImprovementSignals) -> Sequence[ImprovementRule]:
        """Return candidate rules in ``PROPOSED`` (empty when there are no patterns)."""
        ...


@runtime_checkable
class ProactivityStore(Protocol):
    """Durable per-persona store for Bob's proactivity state (drive engine).

    Round-trips the :class:`bob.proactivity.state.ProactivityState` the
    engine reads on each heartbeat tick and writes after it fires or the owner
    acts: the :class:`SocialEnergy` reservoir, ``last_spoke_at`` /
    ``last_user_msg_at`` markers, and the ``proactivity_enabled`` flag toggled by
    ``/quiet`` / ``/wake``. State is per ``persona_id`` so Bobiverse replicas each
    keep their own. The concrete SQLite-backed adapter arrives in BEAD-03.
    """

    async def load(self, persona_id: str) -> ProactivityState:
        """Return the persisted proactivity state for ``persona_id``."""
        ...

    async def save(self, persona_id: str, state: ProactivityState) -> None:
        """Persist ``state`` for ``persona_id`` (replacing any prior state)."""
        ...


@runtime_checkable
class GoalStore(Protocol):
    """Durable per-persona store for Bob's goal graph (Goal Engine, BOB-015).

    Round-trips the :class:`bob.proactivity.goals.graph.GoalGraph` — the goals
    (:class:`bob.proactivity.goals.entities.Goal`) Bob holds and their tasks
    (:class:`bob.proactivity.goals.entities.Task`, each carrying its ``deps`` and the
    ``needs_external_agency`` flag) — so Bob keeps his goals between sessions. State
    is per ``persona_id`` so Bobiverse replicas each keep their own. :meth:`load`
    returns an empty graph for an unseen persona, so the application always has
    something to read. ``save_goal`` / ``save_task`` UPSERT (a goal/task evolves), and
    ``update_goal_state`` / ``update_task_state`` are atomic state moves the approval
    use-case (.2) and the self-directed tick (.3) drive — keeping the authz-before-
    autonomy machine honest (a tick only ever advances an APPROVED/ACTIVE goal). The
    concrete SQLite-backed adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> GoalGraph:
        """Return the persisted goal graph for ``persona_id`` (empty if unseen)."""
        ...

    async def save_goal(self, persona_id: str, goal: Goal) -> None:
        """Persist ``goal`` for ``persona_id`` (UPSERT — an evolving goal is updated)."""
        ...

    async def save_task(self, persona_id: str, task: Task) -> None:
        """Persist ``task`` for ``persona_id`` (UPSERT — deps + flag round-trip)."""
        ...

    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None:
        """Atomically set ``goal_id``'s state (owner approval / tick progress)."""
        ...

    async def update_task_state(
        self, persona_id: str, task_id: str, state: TaskState
    ) -> None:
        """Atomically set ``task_id``'s state (a tick advances one safe task)."""
        ...


@runtime_checkable
class SelfImprovementStore(Protocol):
    """Durable per-persona store for Bob's self-improvement rules (BOB-028 .1).

    Round-trips the :class:`bob.proactivity.self_improvement.ImprovementRule`
    set Bob holds — each rule's observation / adjustment, its :class:`Lever` (from the
    hard allowlist), the bounded ``magnitude``, its :class:`RuleState`, ``origin``,
    ``created_at`` and ``evidence`` — so a curated rule (and its approval state)
    survives a restart. State is per ``persona_id`` so Bobiverse replicas each keep
    their own. :meth:`load` returns an empty tuple for an unseen persona, so the
    application always has something to read. ``save_rule`` UPSERTs (a proposed rule
    is persisted, then re-saved as it evolves), and ``update_rule_state`` is an atomic
    state move the manage-rules use-case (.3) drives — keeping authz-before-autonomy
    honest (only owner approval moves PROPOSED -> APPROVED). The concrete SQLite-backed
    adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:
        """Return the persisted rules for ``persona_id`` (empty tuple if unseen)."""
        ...

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:
        """Persist ``rule`` for ``persona_id`` (UPSERT — an evolving rule is updated)."""
        ...

    async def update_rule_state(
        self, persona_id: str, rule_id: str, state: RuleState
    ) -> None:
        """Atomically set ``rule_id``'s state (owner approval / pause / removal)."""
        ...
