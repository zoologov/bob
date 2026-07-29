# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=infrastructure

"""EpisodicOutgoingActivityStore — Bob's share-of-voice window off the episodic log.

The concrete :class:`~bob.presence.ports.OutgoingActivityStore`: it counts Bob's
recent airtime straight off ``episodic_log``. Each ``message`` episode is one turn
Bob *saw* (``total_seen``); a turn where he actually replied carries a non-NULL
``bob_message_id`` (``bob_sent``); ``distinct_senders`` is the number of distinct
attributed speakers in the window. The window is the last ``window_size`` message
episodes (a rolling recency window), read with parameterised SQL — never an
f-string.

**P0 scope note (honest):** ``episodic_log`` has no ``chat_id`` column yet (the
BOB-066 data-model does not add one — Bob runs a single active chat in P0), so
``chat_id`` is accepted for the port contract + BobNet foresight but the window is
computed over the whole recent stream. When a future migration segments episodes by
chat, the ``WHERE chat_id = ?`` clause drops in here with no change to the domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.presence.outgoing_activity import OutgoingActivity

if TYPE_CHECKING:
    import aiosqlite

# The default rolling window: the last N message-episodes define "recently".
_DEFAULT_WINDOW_SIZE = 20

# Only real conversational turns count toward share of voice.
_MESSAGE_EVENT = "message"


class _ConnectionProvider(Protocol):
    """The connection seam this store needs (realised by SqliteMemoryRepo)."""

    @property
    def connection(self) -> aiosqlite.Connection: ...


class EpisodicOutgoingActivityStore:
    """Builds :class:`OutgoingActivity` by counting recent turns in the episodic log."""

    def __init__(
        self, provider: _ConnectionProvider, *, window_size: int = _DEFAULT_WINDOW_SIZE
    ) -> None:
        self._provider = provider
        self._window_size = window_size

    async def load(self, chat_id: int) -> OutgoingActivity:  # noqa: ARG002 — P0 single-chat; see module docstring
        """Return Bob's rolling activity window over the recent message episodes."""
        async with self._provider.connection.execute(
            "SELECT sender_id, bob_message_id FROM episodic_log "
            "WHERE event_type = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (_MESSAGE_EVENT, self._window_size),
        ) as cursor:
            rows = list(await cursor.fetchall())

        total_seen = len(rows)
        bob_sent = sum(1 for row in rows if row[1] is not None)
        distinct_senders = len({row[0] for row in rows if row[0] is not None})
        return OutgoingActivity(
            bob_sent=bob_sent,
            total_seen=total_seen,
            distinct_senders=distinct_senders,
        )
