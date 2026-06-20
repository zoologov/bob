# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Proactivity application layer — the drive-model → proactive message engine.

Builds on the pure :mod:`bob.domain.proactivity` drive-model: the
:class:`ProactivityEngine` decides cheaply (urge → seeded sample → governance
veto, no LLM) and, only on a genuine fire, runs a Tier-0 gate, composes via the
router, and posts into Bob's topic through the gateway — spending energy and
stamping ``last_spoke_at`` via the :class:`~bob.domain.ports.ProactivityStore`
port. :class:`ProactiveTick` runs the engine on the heartbeat cadence. Time, the
RNG seed, and every port are injected, so the layer holds no globals and is
deterministic in tests.
"""

from __future__ import annotations

from bob.application.proactivity.engine import (
    ProactiveWindowCounter,
    ProactivityEngine,
    ReflectionSalienceSource,
)
from bob.application.proactivity.record_owner_activity import RecordOwnerActivity
from bob.application.proactivity.tick import ProactiveRunner, ProactiveTick

__all__ = [
    "ProactiveRunner",
    "ProactiveTick",
    "ProactiveWindowCounter",
    "ProactivityEngine",
    "RecordOwnerActivity",
    "ReflectionSalienceSource",
]
