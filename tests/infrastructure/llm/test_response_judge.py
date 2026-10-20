# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmResponseJudge — the Tier-0 realisation of the seam (BOB-049 .1).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on
the local provider, and parses the reply into a ``ResponseChoice``. On a parse
failure or a model/router error it RAISES (no silent default) — the
fault-tolerant retry/GUPPI path lives in .3, so here the failure surfaces cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.conversation.adapters.response_judge import LlmResponseJudge
from bob.conversation.addressivity import Addressivity
from bob.conversation.response_choice import ResponseContext, ResponseIntent
from bob.conversation.response_judgment import ResponseJudgeParseError
from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust

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


def _context() -> ResponseContext:
    return ResponseContext(
        text="привет, Боб!",
        interlocutor=Interlocutor(
            sender_id=1,
            display_name="Боб-старший",
            kind=InterlocutorKind.OWNER,
            trust=Trust.TRUSTED,
        ),
        recent_thread="Боб-старший: эй\nbob: да",
        mentions_bob=True,
        reply_to_bob=False,
        addressivity=Addressivity.DIRECTED_TO_BOB,
        others_present=False,
        floor_engaged=True,
        mood_tone="cheerful",
    )


def _judge(reply: str, *, raises: bool = False) -> tuple[LlmResponseJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmResponseJudge(router=router), provider


async def test_builds_tier0_request_and_parses_reply() -> None:
    judge, provider = _judge("intent: reply\nreason: addressed")

    choice = await judge.decide(_context())

    assert choice.intent is ResponseIntent.REPLY
    # The message text is folded into the user prompt sent to the provider.
    assert provider.messages is not None
    user_contents = " ".join(m["content"] for m in provider.messages)
    assert "привет, Боб!" in user_contents


async def test_uses_the_local_response_judge_task() -> None:
    # RESPONSE_JUDGE is pinned Tier-0: a Tier-0-only router proves it never needs
    # a Tier 1 provider.
    judge, _ = _judge("intent: ignore\nreason: bg")
    assert (await judge.decide(_context())).intent is ResponseIntent.IGNORE
    assert TaskType.RESPONSE_JUDGE.value == "response_judge"


async def test_raises_on_unparseable_reply() -> None:
    judge, _ = _judge("I really cannot decide")
    with pytest.raises(ResponseJudgeParseError):
        await judge.decide(_context())


async def test_raises_on_model_error() -> None:
    judge, _ = _judge("intent: reply", raises=True)
    with pytest.raises(RuntimeError):
        await judge.decide(_context())
