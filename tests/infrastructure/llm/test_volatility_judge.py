# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmVolatilityJudge — the Tier-0 realisation of the seam (BOB-057 .1).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on
the local provider, and parses the reply into a ``VolatilityVerdict``. On a
router/model error it RAISES (no silent default) so the caller in .2 safe-defaults
to «не проверять» decoratively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.conversation.adapters.volatility_judge import LlmVolatilityJudge
from bob.conversation.volatility_judgment import VolatilityContext

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


def _context() -> VolatilityContext:
    return VolatilityContext(
        text="какая сейчас ставка ЦБ?",
        recent_thread="Лёша: привет\nbob: да",
    )


def _judge(reply: str, *, raises: bool = False) -> tuple[LlmVolatilityJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmVolatilityJudge(router=router), provider


async def test_builds_tier0_request_and_parses_reply() -> None:
    judge, provider = _judge(
        "needs_check: yes\nquery: текущая ставка ЦБ РФ 2026\ntopic: свежая ставка"
    )

    verdict = await judge.assess(_context())

    assert verdict.needs_check is True
    assert verdict.query == "текущая ставка ЦБ РФ 2026"
    assert verdict.topic == "свежая ставка"
    assert provider.messages is not None
    contents = " ".join(m["content"] for m in provider.messages)
    assert "какая сейчас ставка ЦБ?" in contents


async def test_request_uses_the_local_volatility_judge_task() -> None:
    # VOLATILITY_JUDGE is pinned Tier-0: a Tier-0-only router proves it never needs
    # a Tier 1 provider.
    judge, _ = _judge("needs_check: no\nquery: \ntopic: ")
    verdict = await judge.assess(_context())
    assert verdict.needs_check is False
    assert TaskType.VOLATILITY_JUDGE.value == "volatility_judge"


async def test_conservative_defaults_to_no_check_on_garbled_reply() -> None:
    # A garbled Tier-0 reply must NOT raise — it parses to «не проверять» (US-2).
    judge, _ = _judge("не знаю, честно")
    assert (await judge.assess(_context())).needs_check is False


async def test_raises_on_model_error() -> None:
    judge, _ = _judge("needs_check: no", raises=True)
    with pytest.raises(RuntimeError):
        await judge.assess(_context())
