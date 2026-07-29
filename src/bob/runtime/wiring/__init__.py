# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root wiring — the ``_build_*`` factories that assemble each layer's seams.

The internal factory package of the ``bob.runtime`` composition root (BOB-062.7a): pure
config→value parameter readers plus the per-domain adapter/use-case factories the single
``build_application`` orchestrator calls. Grouped by responsibility (parameters / access /
telegram / capabilities / coding / permission / goals / self_improvement / memory /
proactivity); re-exported here so the composition root imports from one place. It is
``bob.runtime`` (the composition root), NOT ``bob.application.runtime`` (async primitives).
"""

from __future__ import annotations

from bob.runtime.wiring.access import _as_tool_provider, _build_authorizer
from bob.runtime.wiring.capabilities import (
    _build_diagram_renderer,
    _build_introspector,
    _build_registry,
)
from bob.runtime.wiring.coding import _build_coding_assistant, _build_coding_router
from bob.runtime.wiring.goals import _build_goal_engine, _build_pursue_goals_tick
from bob.runtime.wiring.memory import (
    _build_consolidate_memory,
    _build_dedup_facts,
    _build_embedder,
    _build_reranker,
)
from bob.runtime.wiring.parameters import (
    _build_absence_hint_hours,
    _build_acknowledge_reaction_freq,
    _build_addressivity_thresholds,
    _build_brevity_thresholds,
    _build_engagement_mood_lift,
    _build_engagement_thresholds,
    _build_expression_freqs,
    _build_fatigue_rates,
    _build_floor_config,
    _build_floor_enabled,
    _build_introspection_enabled,
    _build_length_guard_enabled,
    _build_length_guard_max_chars,
    _build_max_tasks_per_window,
    _build_offday_thresholds,
    _build_pursuit_enabled,
    _build_pursuit_tick_seconds,
    _build_recent_turns,
    _build_repeat_thresholds,
    _build_require_plan_approval,
    _build_safe_capabilities,
    _build_self_improvement_enabled,
    _build_surface_old_freq,
    _diagram_send_as,
    _fascination_initial_intensity,
    _phantom_evolution_params,
    _resolve_seed,
)
from bob.runtime.wiring.permission import _build_permission_flow
from bob.runtime.wiring.proactivity import (
    _background_tasks,
    _build_proactivity_engine,
)
from bob.runtime.wiring.rhythm import RhythmWiring, build_rhythm_wiring
from bob.runtime.wiring.room_mood import build_room_mood_modulator
from bob.runtime.wiring.self_improvement import (
    _build_self_improvement,
    _SelfImprovement,
)
from bob.runtime.wiring.telegram import _build_multibot

__all__ = [
    "RhythmWiring",
    "_SelfImprovement",
    "_as_tool_provider",
    "_background_tasks",
    "_build_absence_hint_hours",
    "_build_acknowledge_reaction_freq",
    "_build_addressivity_thresholds",
    "_build_authorizer",
    "_build_brevity_thresholds",
    "_build_coding_assistant",
    "_build_coding_router",
    "_build_consolidate_memory",
    "_build_dedup_facts",
    "_build_diagram_renderer",
    "_build_embedder",
    "_build_engagement_mood_lift",
    "_build_engagement_thresholds",
    "_build_expression_freqs",
    "_build_fatigue_rates",
    "_build_floor_config",
    "_build_floor_enabled",
    "_build_goal_engine",
    "_build_introspection_enabled",
    "_build_introspector",
    "_build_length_guard_enabled",
    "_build_length_guard_max_chars",
    "_build_max_tasks_per_window",
    "_build_multibot",
    "_build_offday_thresholds",
    "_build_permission_flow",
    "_build_proactivity_engine",
    "_build_pursue_goals_tick",
    "_build_pursuit_enabled",
    "_build_pursuit_tick_seconds",
    "_build_recent_turns",
    "_build_registry",
    "_build_repeat_thresholds",
    "_build_require_plan_approval",
    "_build_reranker",
    "_build_safe_capabilities",
    "_build_self_improvement",
    "_build_self_improvement_enabled",
    "_build_surface_old_freq",
    "_diagram_send_as",
    "_fascination_initial_intensity",
    "_phantom_evolution_params",
    "_resolve_seed",
    "build_rhythm_wiring",
    "build_room_mood_modulator",
]
