# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=infrastructure

"""LlmRoomReader — the Tier-1 realisation of the reflective read seam (BOB-066 Срез 2.2).

Implements the :class:`~bob.conversation.room_reading.RoomReader` port with one rich
Tier-1 call, mirroring :class:`~bob.conversation.adapters.response_judge.LlmResponseJudge`
(BOB-049): the pure prompt builder folds the
:class:`~bob.conversation.room_reading.RoomReadingContext` into the request, the router
runs it on the Tier-1 model (a ROOM_READ task — «не жалеть LLM» on the reflective read,
per PRINCIPLE-1 liveness > economy), and the pure parser maps the reply to a
:class:`~bob.conversation.room_reading.RoomReading`.

A thin shell on purpose — all read shaping is pure domain. It does NOT swallow failures:
a parse failure (:class:`RoomReadingParseError`) or a model/router error PROPAGATES, so
the PERIPHERY caller (the reflective gate) catches it and safe-defaults to a silent
IGNORE — never Bob acting from a guessed read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.conversation.room_reading import BatchRoomReading, RoomMood
from bob.conversation.room_reading_wire import (
    BATCH_ROOM_READ_SYSTEM_PROMPT,
    ROOM_READ_SYSTEM_PROMPT,
    build_batch_room_prompt,
    build_room_prompt,
    parse_batch_reading,
    parse_room_reading,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.conversation.room_reading import (
        BatchRoomReadingContext,
        RoomReading,
        RoomReadingContext,
    )

__all__ = ["LlmBatchRoomReader", "LlmRoomReader"]


class LlmRoomReader:
    """Read the room via one rich Tier-1 router call (raises on failure)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def read(self, ctx: RoomReadingContext) -> RoomReading:
        """Run the Tier-1 reflective read for ``ctx`` and parse it into a reading.

        Builds the request from the pure prompt builder, runs it on the Tier-1 tier, and
        parses the reply. Any router/model error or an unparseable reply propagates (no
        silent default) for the periphery gate's safe-default IGNORE.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_room_reading(raw)

    @staticmethod
    def _request(ctx: RoomReadingContext) -> LLMRequest:
        """Build the Tier-1 reflective-read request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.ROOM_READ,
            messages=[
                {"role": "system", "content": ROOM_READ_SYSTEM_PROMPT},
                {"role": "user", "content": build_room_prompt(ctx)},
            ],
        )


class LlmBatchRoomReader:
    """Read a whole ambient burst via ONE rich Tier-1 router call (BOB-072).

    Implements the :class:`~bob.conversation.room_reading.BatchRoomReader` port with a single
    ``ROOM_READ`` (Tier-1) call over the pure batch prompt — one holistic read of the settled
    burst instead of one read per message (liveness > economy, PRINCIPLE-4). A thin shell: all
    read shaping is pure domain. The batch parser is TOLERANT, so a returned-but-garbled reply
    becomes a safe all-IGNORE plan of the right length (Bob never acts on a guessed batch);
    a router/model error still PROPAGATES for the application-layer fallback (bead .2). An
    empty burst returns an empty reading WITHOUT calling the model.
    """

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def read(self, batch_ctx: BatchRoomReadingContext) -> BatchRoomReading:
        """Run one Tier-1 stream-read for ``batch_ctx`` and parse per-message readings.

        An empty burst short-circuits to an empty reading (no call). Otherwise the reply is
        parsed tolerantly — a garbled read degrades to a silent all-IGNORE plan, never a raise.
        """
        count = len(batch_ctx.messages)
        if count == 0:
            return BatchRoomReading(readings=(), room_mood=RoomMood.NEUTRAL, reason="")
        raw = await self._router.run(self._request(batch_ctx))
        return parse_batch_reading(raw, count)

    @staticmethod
    def _request(batch_ctx: BatchRoomReadingContext) -> LLMRequest:
        """Build the Tier-1 batch stream-read request for ``batch_ctx``."""
        return LLMRequest(
            task_type=TaskType.ROOM_READ,
            messages=[
                {"role": "system", "content": BATCH_ROOM_READ_SYSTEM_PROMPT},
                {"role": "user", "content": build_batch_room_prompt(batch_ctx)},
            ],
        )
