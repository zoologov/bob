# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_work_journal_recorder`` — the flag switch for distilled work memory.

The distilled-work-memory write path (BOB-087.B1) ships inert behind the bare
``memory.work_journal`` flag (mirroring ``memory.autobiography``). This builder is the ONE
place the flag is read: OFF (the default) → :class:`NoOpWorkJournalRecorder` (zero writes,
memory byte-identical); ON → :class:`DistillingWorkJournalRecorder` over the Tier-0 distiller.
🔴 Nothing is written live until slice C's recall-scoping lands, so the default stays OFF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.coding.usecases.work_journal_recorder import (
    DistillingWorkJournalRecorder,
    NoOpWorkJournalRecorder,
)
from bob.runtime.wiring.work_journal import build_work_journal_recorder

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from datetime import datetime


class _StubProvider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:  # pragma: no cover - never called in wiring
        raise AssertionError("the distiller is not consulted during wiring")


class _StubStore:
    async def save_episode_entity(self, event: object) -> None:  # noqa: ARG002
        raise AssertionError("the store is not written during wiring")


class _StubClock:
    def now(self) -> datetime:  # pragma: no cover - wiring only
        raise AssertionError("the clock is not read during wiring")


def _router() -> LLMRouter:
    return LLMRouter(providers={0: _StubProvider()})


def _build(config: Mapping[str, object]) -> object:
    return build_work_journal_recorder(
        config, router=_router(), store=_StubStore(), clock=_StubClock()
    )


def test_flag_off_yields_noop() -> None:
    assert isinstance(_build({}), NoOpWorkJournalRecorder)


def test_flag_off_explicit_false_yields_noop() -> None:
    assert isinstance(_build({"memory": {"work_journal": False}}), NoOpWorkJournalRecorder)


def test_flag_on_builds_distilling_recorder() -> None:
    recorder = _build({"memory": {"work_journal": True}})
    assert isinstance(recorder, DistillingWorkJournalRecorder)
