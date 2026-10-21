# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmStalenessJudge — the Tier-0 realisation of the seam (BOB-066 Срез W.3).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on the local
provider, and parses the reply into a ``StalenessReading``. A garbled reply parses fail-safe
(all-False → the gate SENDs); a router/model error PROPAGATES so the врезка's decorative caller
degrades to a plain SEND rather than dropping a reply from a silent guess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.presence.adapters.staleness_judge import LlmStalenessJudge
from bob.presence.staleness import ArrivedMessage, StalenessContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """Tier-0 provider returning a fixed reply and recording the messages."""

    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises
        self.messages: Sequence[Mapping[str, str]] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.messages = messages
        if self._raises:
            raise RuntimeError("local model down")
        return self._reply


def _context() -> StalenessContext:
    return StalenessContext(
        drafted="Кофе лучше всего утром",
        newly_arrived=(
            ArrivedMessage(
                sender_id=9,
                text="уже ответил Норман",
                mentions_bob=False,
                reply_to_bob=False,
                from_draft_author=False,
            ),
        ),
    )


def _judge(reply: str, *, raises: bool = False) -> tuple[LlmStalenessJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmStalenessJudge(router=router), provider


async def test_builds_tier0_request_and_parses_reply() -> None:
    judge, provider = _judge(
        "answered: yes\nclosed: no\nclarified: no\nnew_question: no"
    )

    reading = await judge.assess(_context())

    assert reading is not None
    assert reading.answered_by_other is True
    assert reading.new_direct_question is False
    assert provider.messages is not None
    contents = " ".join(m["content"] for m in provider.messages)
    assert "уже ответил Норман" in contents


def test_staleness_judge_task_is_local() -> None:
    assert TaskType.STALENESS_JUDGE.value == "staleness_judge"


async def test_request_runs_on_the_local_tier_only() -> None:
    # STALENESS_JUDGE is pinned Tier-0: a Tier-0-only router proves it never needs Tier 1.
    judge, _ = _judge("answered: no\nclosed: no\nclarified: no\nnew_question: no")
    reading = await judge.assess(_context())
    assert reading is not None
    assert reading.answered_by_other is False


async def test_garbled_reply_reads_as_nothing_shifted() -> None:
    judge, _ = _judge("не знаю, честно")
    reading = await judge.assess(_context())
    assert reading is not None
    assert reading.answered_by_other is False
    assert reading.new_direct_question is False


async def test_raises_on_model_error() -> None:
    judge, _ = _judge("answered: no", raises=True)
    with pytest.raises(RuntimeError):
        await judge.assess(_context())


# --- BOB-116 D13: недоступный Tier-0 — пересмотра нет, а не мёртвый ход ---------------


class _ForbiddenProvider:
    """Tier 0 с отозванным ключом: каждый вызов — настоящий ответ 403."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        url = URL("http://llm.example/v1/chat/completions")
        headers: CIMultiDictProxy[str] = CIMultiDictProxy(CIMultiDict())
        info = aiohttp.RequestInfo(url, "POST", headers, url)
        raise aiohttp.ClientResponseError(info, (), status=403, message="Forbidden")


async def test_an_unavailable_tier0_gives_no_reading_instead_of_raising() -> None:
    judge = LlmStalenessJudge(router=LLMRouter(providers={0: _ForbiddenProvider()}))
    assert await judge.assess(_context()) is None
