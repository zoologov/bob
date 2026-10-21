# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root stream-read wiring — holistic batch read behind ``presence.stream_read``.

The batch «read the stream» component (BOB-072): this is the ONE place the bare
``presence.stream_read`` flag is read and the Tier-1
:class:`~bob.conversation.adapters.room_reader.LlmBatchRoomReader` is assembled. Off (the
default — the whole «человеческое групповое присутствие» epic ships as one piece) the reader is
``None`` so the intake hot path stays byte-identical (the per-message top-k). On → the batch
reader, ready for the ``_handle_batch`` врезка that CONSUMES it (bead .2).

The flag is a BARE boolean (``presence.stream_read``), mirroring ``presence.reflective`` — not
the nested ``<section>.enabled`` convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.adapters.room_reader import LlmBatchRoomReader
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router import LLMRouter
    from bob.conversation.room_reading import BatchRoomReader

__all__ = ["build_batch_room_reader"]


def build_batch_room_reader(
    config: Mapping[str, object], *, router: LLMRouter
) -> BatchRoomReader | None:
    """Assemble the batch stream-reader, or ``None`` when ``presence.stream_read`` is off.

    Off (the default) → ``None`` so intake composes exactly as before (byte-identical). On →
    the Tier-1 :class:`LlmBatchRoomReader` over the shared router, ready to be threaded into the
    dispatcher's ambient-batch врезка (bead .2). This builder never consults the model.
    """
    if not _flag(_section(config, "presence"), "stream_read"):
        return None
    return LlmBatchRoomReader(router=router)
