# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmReactionJudge — the Tier-0 realisation of the seam (BOB-050 .2).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on the
local provider, and parses the reply into a ``ReactionMeaning``. On a parse failure or
a model/router error it RAISES (no silent default) — the decorative perceiving path
catches the failure and drops the reaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.personality.adapters.reaction_judge import LlmReactionJudge
from bob.personality.reaction_judgment import ReactionJudgeParseError
from bob.personality.reaction_meaning import ReactionContext
from bob.social.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)

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


def _context() -> ReactionContext:
    return ReactionContext(
        emoji=("❤",),
        added=True,
        bob_message_text="я правда рад",
        reactor=Interlocutor(
            sender_id=1,
            display_name="Боб-старший",
            kind=InterlocutorKind.OWNER,
            trust=Trust.TRUSTED,
        ),
        reactor_warmth=0.4,
        recent_thread="",
    )


def _judge(reply: str, *, raises: bool = False) -> tuple[LlmReactionJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmReactionJudge(router=router), provider


async def test_builds_tier0_request_and_parses_reply() -> None:
    judge, provider = _judge(
        "interpretation: тронуло\nsentiment: warm\nintensity: high\nacknowledge: yes"
    )

    meaning = await judge.interpret(_context())

    assert meaning.interpretation == "тронуло"
    assert meaning.mood_delta.valence > 0
    assert provider.messages is not None
    user_contents = " ".join(m["content"] for m in provider.messages)
    assert "я правда рад" in user_contents


async def test_uses_the_local_reaction_judge_task() -> None:
    judge, _ = _judge("interpretation: тепло\nsentiment: warm\nintensity: low")
    assert (await judge.interpret(_context())).mood_delta.valence > 0
    assert TaskType.REACTION_JUDGE.value == "reaction_judge"


async def test_raises_on_unparseable_reply() -> None:
    judge, _ = _judge("I cannot tell")
    with pytest.raises(ReactionJudgeParseError):
        await judge.interpret(_context())


async def test_raises_on_model_error() -> None:
    judge, _ = _judge("interpretation: x\nsentiment: warm", raises=True)
    with pytest.raises(RuntimeError):
        await judge.interpret(_context())
