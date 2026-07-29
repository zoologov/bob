# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""OutgoingActivity — Bob's rolling per-chat share-of-voice window (pure VO).

A tiny value object over a per-``chat_id`` rolling window: how many turns Bob
spoke into (``bob_sent``) out of how many turns he saw (``total_seen``), plus how
many distinct participants were active in that window (``distinct_senders``). The
window is participant-agnostic — a message from a human or a Bobiverse replica
counts the same (BobNet foresight), because share of voice is about *how much of
the room's airtime is Bob's*, not who else is speaking. The store adapter fills it
from the episodic log; the :class:`~bob.presence.share_of_voice.ShareOfVoicePolicy`
reads :attr:`share` + :attr:`distinct_senders` to decide the ambient ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutgoingActivity:
    """Bob's share-of-voice window for one chat: sent vs seen vs distinct speakers."""

    bob_sent: int
    total_seen: int
    distinct_senders: int = 0

    def __post_init__(self) -> None:
        if self.bob_sent < 0:
            raise ValueError(f"bob_sent must be non-negative, got {self.bob_sent}")
        if self.total_seen < 0:
            raise ValueError(f"total_seen must be non-negative, got {self.total_seen}")
        if self.bob_sent > self.total_seen:
            raise ValueError(
                f"bob_sent ({self.bob_sent}) cannot exceed total_seen ({self.total_seen})"
            )
        if self.distinct_senders < 0:
            raise ValueError(
                f"distinct_senders must be non-negative, got {self.distinct_senders}"
            )

    @property
    def share(self) -> float:
        """Fraction of seen turns Bob spoke into, in ``[0, 1]`` (empty window → 0.0).

        An empty window (Bob has seen nothing yet) reads as zero share, so a fresh
        chat never trips the ambient ceiling — Bob is free to join in.
        """
        if self.total_seen == 0:
            return 0.0
        return self.bob_sent / self.total_seen
