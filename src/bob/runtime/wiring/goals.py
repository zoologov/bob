# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root goal wiring — the Goal Engine + the self-directed pursuit tick.

Builds the per-persona :class:`SqliteGoalStore` + double-gated :class:`PlanGoal`, and — only
when ``goals.pursuit_enabled`` — the self-directed :class:`PursueGoalsTick` restricted to the
``goals.safe_capabilities`` allowlist over the shared governance. Off → the pursuit tick is
``None`` (the schedule is exactly as before). Part of the ``bob.runtime`` composition root
(BOB-062.7a).
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from bob.capabilities.usecases import SafeCapabilityDispatcher
from bob.proactivity.adapters import RepoProactivitySources, SqliteGoalStore
from bob.proactivity.governance import Governance
from bob.proactivity.usecases.plan_goal import LlmPlanner, PlanGoal
from bob.proactivity.usecases.pursue_goals import PursueGoalsTick
from bob.runtime.config import _BOB_PERSONA, _int, _section
from bob.runtime.wiring.parameters import (
    _build_max_tasks_per_window,
    _build_pursuit_enabled,
    _build_require_plan_approval,
    _build_safe_capabilities,
    _resolve_seed,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.capabilities.usecases import CapabilityRegistry
    from bob.infrastructure.persistence import SqliteConnection
    from bob.kernel.ports import Clock, ReplyGateway
    from bob.memory.adapters import SqliteMemoryRepo
    from bob.personality.state import PersonalityState
    from bob.proactivity.adapters import SqliteProactivityStore


def _build_goal_engine(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    repo: SqliteConnection,
) -> tuple[SqliteGoalStore, PlanGoal]:
    """Assemble the Goal Engine store + plan use-case (BOB-015 .2).

    The per-persona :class:`SqliteGoalStore` round-trips Bob's goals; the
    :class:`LlmPlanner` decomposes an APPROVED goal via the Tier-1 router (strict
    JSON, ``needs_external_agency`` classification); :class:`PlanGoal` saves the tasks
    and shows the owner the plan, holding the goal at APPROVED until the plan is also
    approved (``goals.require_plan_approval``, default true — the double gate). No
    self-directed tick is wired here — that is .3's job.
    """
    store = SqliteGoalStore(repo)
    plan_goal = PlanGoal(
        planner=LlmPlanner(router=router),
        store=store,
        persona_id=_BOB_PERSONA,
        require_plan_approval=_build_require_plan_approval(config),
    )
    return store, plan_goal


def _build_pursue_goals_tick(
    config: Mapping[str, object],
    *,
    goal_store: SqliteGoalStore,
    pursuit_store: SqliteProactivityStore,
    history: SqliteProactivityStore,
    registry: CapabilityRegistry,
    gateway: ReplyGateway,
    personality: PersonalityState,
    repo: SqliteMemoryRepo,
    clock: Clock,
    seed: int | None,
) -> PursueGoalsTick | None:
    """Assemble the self-directed goal-pursuit tick, or ``None`` when off (BOB-015 .3).

    Built ONLY when ``goals.pursuit_enabled`` is on (conservative default off): the
    self-directed tick is the most safety-critical path, so it stays unwired unless
    the owner deliberately enables it (unwired → the runtime behaves exactly as
    before). It reuses the SAME :class:`Governance` ceilings and the kill-switch the
    proactive chat uses (one config governs both reach-out paths), the Goal Engine
    store (only an APPROVED/ACTIVE goal is ever advanced), and a
    :class:`SafeCapabilityDispatcher` over the registry restricted to
    ``goals.safe_capabilities`` — the hard boundary that keeps an external-agency or
    arbitrary capability unreachable on the autonomous path. The window-count seam
    (over ``goal_progress`` episodes) enforces ``goals.max_tasks_per_window`` on top
    of governance. The seed is shared so the autonomous choice is reproducible.
    """
    if not _build_pursuit_enabled(config):
        return None
    telegram = _section(config, "telegram")
    sources = RepoProactivitySources(repo, clock=clock)
    dispatcher = SafeCapabilityDispatcher(
        registry, allowlist=_build_safe_capabilities(config)
    )
    return PursueGoalsTick(
        persona_id=_BOB_PERSONA,
        chat_id=_int(telegram, "chat_id", 0),
        goal_store=goal_store,
        pursuit_store=pursuit_store,
        governance=Governance(),
        history=history,
        window=sources,
        dispatcher=dispatcher,
        episodes=repo,
        gateway=gateway,
        personality=personality,
        clock=clock,
        # Deterministic-by-seed, NOT cryptographic: the same seed knob that pins the
        # proactive draw also pins which safe capability the tick picks.
        rng=random.Random(_resolve_seed(config, seed)),  # noqa: S311
        safe_capabilities=_build_safe_capabilities(config),
        max_tasks_per_window=_build_max_tasks_per_window(config),
    )
