# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=domain

"""ProactivityState — the per-persona proactivity state the engine persists.

A plain value object the :class:`bob.domain.ports.ProactivityStore` round-trips
to durable storage: the current :class:`SocialEnergy` reservoir, when Bob last
spoke proactively, when the owner last wrote, and whether proactivity is enabled
(the owner's ``/quiet`` / ``/wake`` flag). No behaviour, no I/O — just the fields
the engine (BEAD-02) reads on a tick and the store (BEAD-03) saves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from bob.proactivity.social_energy import SocialEnergy


@dataclass(frozen=True, slots=True)
class ProactivityState:
    """Per-persona proactivity state persisted between heartbeat ticks."""

    social_energy: SocialEnergy
    last_spoke_at: datetime | None
    last_user_msg_at: datetime | None
    proactivity_enabled: bool
