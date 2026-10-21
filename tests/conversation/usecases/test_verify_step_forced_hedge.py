# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Forced-verify failure modes (BOB-066 Срез 2.2, C11).

A reflective ``wants_web`` forces the EXISTING verify pass — so it must REUSE the same
honest-hedge behaviour the judged path already has, not a new path. These pin that a
forced search that FAILS / TIMES OUT / returns EMPTY degrades to the honest hedge note
(US-6: never a confident stale number, never a fabrication) while still skipping the
volatility judge (Bob already chose to look).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from bob.capabilities.ports import WebSearchResult
from bob.conversation.usecases.verify_step import (
    _FORCED_TOPIC_MAX_CHARS,
    _VERIFY_HEDGE_NOTE,
    VerifyInterimAnnouncer,
    VerifyStep,
)

if TYPE_CHECKING:
    from bob.conversation.ports import VerifySearch
    from bob.conversation.volatility_judgment import VolatilityContext, VolatilityVerdict


class _ExplodingJudge:
    """Must NEVER be consulted on a forced verify (Bob already decided to look)."""

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        raise AssertionError("forced verify must not call the volatility judge")


class _RaisingSearch:
    async def search(self, query: str) -> WebSearchResult:
        raise RuntimeError("search backend down")


class _SlowSearch:
    """A provider that overruns the timeout — the step must hedge, not stall."""

    async def search(self, query: str) -> WebSearchResult:
        await asyncio.sleep(10)
        raise AssertionError("should have timed out")  # pragma: no cover


class _EmptySearch:
    async def search(self, query: str) -> WebSearchResult:
        return WebSearchResult(answer="   ")


def _no_announcer(*, chat_id: int, sender_name: str) -> VerifyInterimAnnouncer:
    raise AssertionError("no interim without chat_id")


def _step(provider: VerifySearch, *, timeout: float = 1.0) -> VerifyStep:
    return VerifyStep(
        verify_judge=_ExplodingJudge(),  # must not be called on a forced verify
        verify_provider=provider,
        verify_timeout_seconds=timeout,
        announcer_factory=_no_announcer,
    )


_TEXT = "какая сейчас ключевая ставка ЦБ и когда следующее заседание совета директоров?"


@pytest.mark.asyncio
async def test_forced_search_failure_hedges_honestly() -> None:
    note = await _step(_RaisingSearch()).note(_TEXT, [], forced=True)
    assert note == _VERIFY_HEDGE_NOTE.format(topic=_TEXT[:_FORCED_TOPIC_MAX_CHARS])


@pytest.mark.asyncio
async def test_forced_search_timeout_hedges_without_stalling() -> None:
    note = await _step(_SlowSearch(), timeout=0.01).note(_TEXT, [], forced=True)
    assert note == _VERIFY_HEDGE_NOTE.format(topic=_TEXT[:_FORCED_TOPIC_MAX_CHARS])


@pytest.mark.asyncio
async def test_forced_empty_answer_hedges() -> None:
    note = await _step(_EmptySearch()).note(_TEXT, [], forced=True)
    assert note == _VERIFY_HEDGE_NOTE.format(topic=_TEXT[:_FORCED_TOPIC_MAX_CHARS])


@pytest.mark.asyncio
async def test_forced_topic_is_trimmed_to_the_cap() -> None:
    # The hedge topic (and the interim line) uses the SHORT trimmed turn text, so a long
    # message never floods the note.
    topic = _TEXT[:_FORCED_TOPIC_MAX_CHARS]
    assert len(topic) <= _FORCED_TOPIC_MAX_CHARS
    note = await _step(_RaisingSearch()).note(_TEXT, [], forced=True)
    assert topic in note
