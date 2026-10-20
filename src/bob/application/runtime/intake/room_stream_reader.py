# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""RoomStreamReader (BOB-072) — a settled ambient burst → one per-message reading.

The application-side of the holistic stream-read врезка: the intake worker splits a settled
burst into focal (answered deterministically — INV-1) and ambient, then hands the WHOLE
ambient part here for ONE holistic «read the stream» (liveness > economy, PRINCIPLE-4) rather
than a scripted top-k over N per-message reads. This reader folds the burst into a
:class:`~bob.conversation.room_reading.BatchRoomReadingContext` (an attributed stream + Bob's
current tone), runs the injected
:class:`~bob.conversation.room_reading.BatchRoomReader` once, and returns exactly one
:class:`~bob.conversation.room_reading.RoomReading` per message IN ARRIVAL ORDER.

🔴 A reader failure NEVER propagates: it degrades to a safe all-IGNORE plan of the right
length, so the intake worker still persists + floor-advances every ambient message (INV-S2 —
the thread stays intact, BOB-071 Seam B), never Bob acting on a guessed read. The pure verdict
projection stays in :func:`~bob.conversation.room_verdict.decide_batch`; this reader only
produces the per-message readings the turn gate applies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from bob.conversation.room_reading import (
    BatchAmbientMessage,
    BatchRoomReadingContext,
    ReflectiveIntent,
    RoomMood,
    RoomReading,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from bob.conversation.room_reading import BatchRoomReader
    from bob.kernel.events import MessageReceived
    from bob.kernel.interlocutor import InterlocutorKind

    type _MoodTone = Callable[[], str]
    type _PerceiveKind = Callable[[MessageReceived], Awaitable[InterlocutorKind]]

logger = logging.getLogger(__name__)

__all__ = ["SILENT_IGNORE_READING", "AmbientBatchReader", "RoomStreamReader"]

# Neutral per-message floor / interest hints for the batch read (BOB-072 .2): the batch context
# carries WHO/WHAT/WHEN (attribution the read reasons by) with neutral floor/interest signals —
# they are SIGNALS the read weighs, not rules, so a neutral default is honest; richer per-message
# floor/interest hints are a later quality refinement (they never gate the split/persist mechanics
# this bead delivers). Kept as named constants (no magic literals).
_NEUTRAL_FLOOR_HOLDER = "none"
_NEUTRAL_FLOOR_PARTICIPANT = False
_NEUTRAL_INTEREST = 0.5

# The safe silent reading an ambient message degrades to when the whole batch read fails — the
# intake worker still persists it (Seam B), never Bob acting on a guess. The SAME reading stamps a
# queue-level superseded message (BOB-072 stale-coalesce): dropped from the read, still persisted.
SILENT_IGNORE_READING = RoomReading(
    situation="",
    pairings=(),
    room_mood=RoomMood.NEUTRAL,
    intent=ReflectiveIntent.IGNORE,
    addressee_id=None,
    salience=0.0,
    emoji=None,
    wants_web=False,
    reason="batch read failed",
)


@runtime_checkable
class AmbientBatchReader(Protocol):
    """The seam the intake worker consumes: a settled ambient burst → per-message readings.

    Returns exactly one :class:`RoomReading` per input message IN ARRIVAL ORDER (a safe
    all-IGNORE plan on failure — never raises), so the worker can apply each verdict and
    persist + floor-advance every ambient message (INV-S2).
    """

    async def read(self, messages: Sequence[MessageReceived]) -> Sequence[RoomReading]: ...


class RoomStreamReader:
    """Read a whole settled ambient burst into one per-message reading (BOB-072)."""

    def __init__(
        self,
        *,
        reader: BatchRoomReader,
        mood_tone: _MoodTone,
        perceive_kind: _PerceiveKind | None = None,
    ) -> None:
        self._reader = reader
        self._mood_tone = mood_tone
        self._perceive_kind = perceive_kind

    async def read(self, messages: Sequence[MessageReceived]) -> Sequence[RoomReading]:
        """Fold ``messages`` into one batch read → exactly one reading per message (in order).

        An empty burst returns no readings without a read. Otherwise the ONE injected batch
        reader runs; a failure degrades to a safe all-IGNORE plan and a short plan (a contract
        breach) is padded — so the result ALWAYS has one reading per message and the worker
        persists every ambient turn (INV-S2).
        """
        count = len(messages)
        if count == 0:
            return ()
        try:
            batch_ctx = await self._batch_context(messages)
            reading = await self._reader.read(batch_ctx)
            plan = list(reading.readings)
        except Exception:
            logger.exception("batch stream-read failed (ambient burst → all-IGNORE)")
            plan = []
        if len(plan) < count:
            plan.extend(SILENT_IGNORE_READING for _ in range(count - len(plan)))
        return plan[:count]

    async def _batch_context(
        self, messages: Sequence[MessageReceived]
    ) -> BatchRoomReadingContext:
        """Fold the attributed burst (+ each author's social kind) + Bob's tone into the read.

        Each message carries its perceived :class:`InterlocutorKind` (BOB-078 B) when a kind
        resolver is wired — so the read weighs a GUEST/newcomer's warm reply as salient, not
        low-salience chatter; unwired, ``kind`` stays ``None`` (byte-identical baseline).
        """
        ambient = tuple(
            [
                BatchAmbientMessage(
                    sender_id=message.sender_id or 0,
                    sender_name=message.sender_name or str(message.sender_id or "?"),
                    text=message.text,
                    ts=float(index),
                    floor_holder=_NEUTRAL_FLOOR_HOLDER,
                    floor_participant=_NEUTRAL_FLOOR_PARTICIPANT,
                    interest=_NEUTRAL_INTEREST,
                    kind=await self._kind_of(message),
                )
                for index, message in enumerate(messages)
            ]
        )
        return BatchRoomReadingContext(
            messages=ambient,
            recent_thread="",
            mood_tone=self._mood_tone(),
            others_present=True,
        )

    async def _kind_of(self, message: MessageReceived) -> InterlocutorKind | None:
        """Perceive the sender's social kind (``None`` when no resolver is wired)."""
        if self._perceive_kind is None:
            return None
        return await self._perceive_kind(message)
