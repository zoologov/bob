# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root self-improvement wiring — the apply + reflect-tick seams (BOB-028).

Assembles the metacognition pieces ONLY when the master switch is on AND the rule store is
wired: the APPROVED-only :class:`ActiveRulesReader` (soft tilts into HandleMessage), the
:class:`DetectPatterns` + :class:`AnnounceProposedRules` reflect-tick seams. Off / no store →
every piece is ``None`` (the runtime behaves exactly as before BOB-028). Part of the
``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.proactivity.usecases.announce_rules import AnnounceProposedRules
from bob.proactivity.usecases.detect_patterns import DetectPatterns, LlmPatternDetector
from bob.proactivity.usecases.self_improvement_sources import ActiveRulesReader
from bob.runtime.config import (
    _BOB_PERSONA,
    _DEFAULT_SI_MAX_ACTIVE_RULES,
    _DEFAULT_SI_MAX_MAGNITUDE,
    _float_or,
    _int,
    _section,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.application.usecases.handle_message import ReplyGateway
    from bob.kernel.ports import Clock
    from bob.proactivity.adapters import SqliteSelfImprovementStore


@dataclass(frozen=True)
class _SelfImprovement:
    """The wired self-improvement pieces (BOB-028 .3), all None when the switch is off.

    ``reader`` is the apply-side seam HandleMessage reads (APPROVED-only soft tilts);
    ``detect_patterns`` + ``announce_rules`` are the reflect-tick seams; ``max_magnitude``
    is the soft-tilt ceiling. Off → ``reader`` / ``detect_patterns`` / ``announce_rules``
    are None and the magnitude is the default, so every consumer is a no-op.
    """

    reader: ActiveRulesReader | None
    detect_patterns: DetectPatterns | None
    announce_rules: AnnounceProposedRules | None
    max_magnitude: float


def _build_self_improvement(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    rule_store: SqliteSelfImprovementStore | None,
    gateway: ReplyGateway,
    chat_id: int,
    clock: Clock,
) -> _SelfImprovement:
    """Assemble the self-improvement apply + reflect-tick pieces, or no-ops (BOB-028 .3).

    Built ONLY when the master switch is on AND the rule store is wired: the
    :class:`ActiveRulesReader` (APPROVED-only soft tilts into HandleMessage), the
    :class:`DetectPatterns` reflect-tick seam (Tier-``detector_tier`` LLM detector →
    candidate PROPOSED rules, capped by ``max_active_rules``; it runs on empty signals
    for now — a signal-collection adapter is a later step), and the
    :class:`AnnounceProposedRules` reflect-tick seam (Bob tactfully voices ONE fresh
    proposal into his topic). Off / no store → every piece is None and the magnitude is
    the config ceiling, so the runtime behaves exactly as before BOB-028.
    """
    section = _section(config, "self_improvement")
    max_magnitude = _float_or(section, "max_magnitude", _DEFAULT_SI_MAX_MAGNITUDE)
    if rule_store is None:
        return _SelfImprovement(
            reader=None,
            detect_patterns=None,
            announce_rules=None,
            max_magnitude=max_magnitude,
        )
    detector = LlmPatternDetector(router=router, clock=clock)
    detect_patterns = DetectPatterns(
        detector=detector,
        store=rule_store,
        persona_id=_BOB_PERSONA,
        max_active_rules=_int(section, "max_active_rules", _DEFAULT_SI_MAX_ACTIVE_RULES),
    )
    announce_rules = AnnounceProposedRules(
        store=rule_store,
        gateway=gateway,
        chat_id=chat_id,
        persona_id=_BOB_PERSONA,
    )
    reader = ActiveRulesReader(store=rule_store, persona_id=_BOB_PERSONA)
    return _SelfImprovement(
        reader=reader,
        detect_patterns=detect_patterns,
        announce_rules=announce_rules,
        max_magnitude=max_magnitude,
    )
