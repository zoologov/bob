# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the FORCED verify path (BOB-066 Срез 2.2, C11).

A reflective read that set ``wants_web`` forces the EXISTING verify pass:
``VerifyStep.note(..., forced=True)`` must SKIP the volatility judge (Bob already chose
to look) and search on the turn's own text — reusing the verify/web seam, not a new one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.ports import WebSearchResult
from bob.conversation.usecases.verify_step import (
    _VERIFY_GROUNDED_NOTE,
    VerifyInterimAnnouncer,
    VerifyStep,
)

if TYPE_CHECKING:
    from bob.conversation.ports import VerifySearch
    from bob.conversation.volatility_judgment import (
        VolatilityContext,
        VolatilityJudge,
        VolatilityVerdict,
    )


class _ExplodingJudge:
    """A judge that must NEVER be consulted on a forced verify."""

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        raise AssertionError("forced verify must not call the volatility judge")


class _FakeSearch:
    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        return WebSearchResult(answer=self._answer)


def _no_announcer(*, chat_id: int, sender_name: str) -> VerifyInterimAnnouncer:
    raise AssertionError("no interim without chat_id")


def _step(
    judge: VolatilityJudge | None, provider: VerifySearch | None
) -> VerifyStep:
    return VerifyStep(
        verify_judge=judge,
        verify_provider=provider,
        verify_timeout_seconds=1.0,
        announcer_factory=_no_announcer,
    )


@pytest.mark.asyncio
async def test_forced_skips_the_judge_and_searches_the_turn_text() -> None:
    provider = _FakeSearch(answer="сейчас 21%")
    step = _step(_ExplodingJudge(), provider)

    note = await step.note("какая сейчас ставка ЦБ?", [], forced=True)

    assert note == _VERIFY_GROUNDED_NOTE.format(answer="сейчас 21%")
    assert provider.queries == ["какая сейчас ставка ЦБ?"]


@pytest.mark.asyncio
async def test_forced_without_a_provider_is_inert() -> None:
    # No web capability wired → forced verify still short-circuits to "" (no crash).
    step = _step(_ExplodingJudge(), None)
    assert await step.note("какая сейчас ставка?", [], forced=True) == ""


@pytest.mark.asyncio
async def test_unforced_with_no_judge_is_inert() -> None:
    # Regression: the default path (forced=False) is unchanged — an unwired judge means
    # no check ("").
    step = _step(None, _FakeSearch(answer="x"))
    assert await step.note("что делаешь?", [], forced=False) == ""
