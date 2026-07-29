# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""Presence domain — Bob's pure "rhythm of a living participant" logic (no I/O).

The ritm-слой of «человеческое групповое присутствие» (BOB-066) as deterministic
value objects and policies: :class:`OutgoingActivity` (a rolling share-of-voice
window), :class:`ShareOfVoicePolicy` (the soft ambient ceiling — focus bypasses,
never mutes), :class:`NaturalDelayPolicy` (the human floor under reply speed),
:class:`ReactionBudget` (a separate, gentle like budget), and :class:`RhythmConfig`
(their tunables). Time and randomness are injected; nothing here touches a clock, a
model, or Telegram. The application coordinator (``DelayedTurn``) and the episodic
store adapter build on these; a feature flag keeps them inert until the epic ships.
"""

from __future__ import annotations

from bob.presence.natural_delay import NaturalDelayPolicy
from bob.presence.outgoing_activity import OutgoingActivity
from bob.presence.reaction_budget import ReactionBudget
from bob.presence.rhythm_config import RhythmConfig
from bob.presence.share_of_voice import ShareOfVoicePolicy

__all__ = [
    "NaturalDelayPolicy",
    "OutgoingActivity",
    "ReactionBudget",
    "RhythmConfig",
    "ShareOfVoicePolicy",
]
