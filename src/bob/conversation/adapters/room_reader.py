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
from bob.conversation.room_reading_wire import (
    ROOM_READ_SYSTEM_PROMPT,
    build_room_prompt,
    parse_room_reading,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.conversation.room_reading import RoomReading, RoomReadingContext

__all__ = ["LlmRoomReader"]


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
