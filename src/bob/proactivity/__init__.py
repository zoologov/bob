# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""Proactivity domain — Bob's pure "drive to reach out" logic (no I/O, no LLM).

The foundation of proactive companionship as deterministic value objects and
domain services: :class:`SocialEnergy` (a recover/spend reservoir),
:class:`UrgeModel` (the urge formula), :class:`Governance` (veto ceilings),
:class:`ProactiveDecider` (urge → seeded sample → veto), and
:class:`ProactivityState` (the per-persona state the store round-trips). Time and
randomness are injected; nothing here touches a clock, a model, or Telegram. The
engine (BEAD-02) and the persistence adapter (BEAD-03) build on these.
"""

from __future__ import annotations

from bob.proactivity.decision import ProactiveDecider, urge_to_probability
from bob.proactivity.governance import (
    Governance,
    GovernanceConfig,
    ProactiveHistory,
)
from bob.proactivity.social_energy import SocialEnergy
from bob.proactivity.state import ProactivityState
from bob.proactivity.urge import UrgeModel

__all__ = [
    "Governance",
    "GovernanceConfig",
    "ProactiveDecider",
    "ProactiveHistory",
    "ProactivityState",
    "SocialEnergy",
    "UrgeModel",
    "urge_to_probability",
]
