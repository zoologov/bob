# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""Presence ports — the outward seams the rhythm layer needs (interfaces only).

The rhythm policies are pure, but the ambient ceiling needs to know how much Bob
has been speaking in a chat — that lives in the durable episodic log. This module
declares the seam as a structural :class:`typing.Protocol` with no implementation;
the concrete SQLite/episodic-backed adapter lives in ``bob.presence.adapters``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.presence.outgoing_activity import OutgoingActivity


@runtime_checkable
class OutgoingActivityStore(Protocol):
    """Read seam: Bob's rolling share-of-voice window for one chat.

    Returns the :class:`~bob.presence.outgoing_activity.OutgoingActivity` — how many
    of the recent turns in ``chat_id`` Bob spoke into, out of how many he saw, plus
    the distinct speakers active — that the
    :class:`~bob.presence.share_of_voice.ShareOfVoicePolicy` reads to set the ambient
    ceiling. The concrete adapter counts over the episodic log; a deterministic fake
    serves fixed windows in tests with no I/O.
    """

    async def load(self, chat_id: int) -> OutgoingActivity:
        """Return Bob's current rolling activity window for ``chat_id``."""
        ...
