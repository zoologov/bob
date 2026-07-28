# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""FloorManager — resolve + advance the conversation floor for a turn (BOB-025).

The turn's conversation-floor concern in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 1, behavior-preserving). Over the per-message
addressivity (BOB-023) lives a tracker of who currently holds the "talking turn" in a
thread:

* :meth:`resolve_effective` RAISES an ``AMBIENT`` message to ``DIRECTED_TO_BOB`` while
  Bob holds a live floor (continuity — the owner keeps talking to Bob without re-tagging
  every message); and
* :meth:`advance_after_turn` advances + persists the floor after a turn on the RAW
  per-message addressivity + whether Bob actually replied.

🔴 The advance is called on ALL branches (SILENT / REACT / react-only / happy-path), so
the floor always reflects the real signal. Best-effort: a flaky floor store can never
break a turn. Unwired store or ``floor_enabled`` false → both methods are inert (exactly
BOB-023 behaviour). This collaborator takes primitive ids (``chat_id`` / ``sender_id``),
never the application ``MessageReceived`` event, so the conversation vertical stays free
of an inward application dependency.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.conversation.conversation_floor import (
    FloorConfig,
    advance_floor,
    resolve_addressivity,
)

if TYPE_CHECKING:
    from bob.conversation.addressivity import Addressivity
    from bob.conversation.ports import ConversationFloorStore
    from bob.kernel.ports import Clock

logger = logging.getLogger(__name__)


class FloorManager:
    """Resolve + advance the conversation floor for one turn (BOB-025)."""

    def __init__(
        self,
        *,
        floor_store: ConversationFloorStore | None,
        floor_config: FloorConfig,
        floor_enabled: bool,
        clock: Clock,
    ) -> None:
        self._floor_store = floor_store
        self._floor_config = floor_config
        self._floor_enabled = floor_enabled
        self._clock = clock

    async def resolve_effective(
        self, chat_id: int, per_message: Addressivity
    ) -> Addressivity:
        """Raise per-message addressivity by the conversation floor (BOB-025).

        With the floor wired AND enabled, an ``AMBIENT`` message in a thread where Bob
        holds a live floor is raised to ``DIRECTED_TO_BOB`` (continuity); the floor is
        loaded for ``(chat_id, thread_id)``. Floor unwired or disabled → the per-message
        classification is returned unchanged (BOB-023 behaviour). Best-effort: a flaky
        floor store can never break a turn — on a load/resolve failure Bob falls back to
        the per-message BOB-023 classification (a hiccup must never mute him), mirroring
        the advance side.
        """
        if self._floor_store is None or not self._floor_enabled:
            return per_message
        try:
            floor = await self._floor_store.load(chat_id, self._thread_id())
            return resolve_addressivity(
                per_message, floor, now=self._clock.now(), config=self._floor_config
            )
        except Exception:
            logger.exception(
                "resolving the conversation floor failed; using per-message addressivity"
            )
            return per_message

    async def advance_after_turn(
        self,
        *,
        chat_id: int,
        sender_id: int | None,
        per_message: Addressivity,
        directed_to_id: int | None,
        bob_replied: bool,
    ) -> None:
        """Advance + persist the conversation floor after a turn (BOB-025).

        Reloads the floor for the thread, advances it on the RAW per-message addressivity
        (the floor reflects the real signal) plus whether Bob actually replied
        (``bob_replied`` sticks the floor to him on an ENGAGE turn; a SILENT/REACT turn
        passes ``False`` so idle_streak / decay are counted), then UPSERTs it. No-op when
        the floor is unwired or disabled (BOB-023 behaviour). Best-effort: a flaky floor
        store can never break a turn that has already acted.
        """
        if self._floor_store is None or not self._floor_enabled:
            return
        thread_id = self._thread_id()
        try:
            floor = await self._floor_store.load(chat_id, thread_id)
            new_floor = advance_floor(
                floor,
                addressivity=per_message,
                sender_id=sender_id,
                directed_to_id=directed_to_id,
                bob_replied=bob_replied,
                now=self._clock.now(),
                config=self._floor_config,
            )
            await self._floor_store.save(chat_id, thread_id, new_floor)
        except Exception:
            logger.exception("advancing the conversation floor failed (ignored)")

    @staticmethod
    def _thread_id() -> int | None:
        """The thread key for the conversation floor (BOB-025).

        The floor is a property of one running exchange (Bob's forum topic). The
        application event does not yet carry a forum ``thread_id``, so the floor is
        keyed by ``chat_id`` alone for now (``None`` = main chat / no topic — the store's
        sentinel). Kept as a seam so a real per-topic key threads through later.
        """
        return None
