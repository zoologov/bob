# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_batch_room_reader`` — the composition switch for holistic stream-read.

The batch stream-read component (BOB-072) ships inert behind the bare ``presence.stream_read``
flag (mirroring ``presence.reflective``). This builder is the ONE place the flag is read: off
(the default) → ``None`` so the hot path is byte-identical; on → the Tier-1
``LlmBatchRoomReader``. The dispatcher врезка that CONSUMES it lands in bead .2 — here the
component only comes into being behind its flag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.conversation.adapters.room_reader import LlmBatchRoomReader
from bob.runtime.wiring.stream_read import build_batch_room_reader

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _StubProvider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:  # pragma: no cover - never called in wiring
        raise AssertionError("the reader is not consulted during wiring")


def _router() -> LLMRouter:
    return LLMRouter(providers={0: _StubProvider(), 1: _StubProvider()})


def test_flag_off_yields_no_reader() -> None:
    assert build_batch_room_reader({}, router=_router()) is None


def test_flag_off_explicit_false_yields_no_reader() -> None:
    config = {"presence": {"stream_read": False}}
    assert build_batch_room_reader(config, router=_router()) is None


def test_flag_on_builds_the_reader() -> None:
    config = {"presence": {"stream_read": True}}
    reader = build_batch_room_reader(config, router=_router())
    assert isinstance(reader, LlmBatchRoomReader)
