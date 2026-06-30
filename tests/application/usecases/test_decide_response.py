# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for DecideResponse — the thin semantic-response use-case (BOB-049 .1).

The use-case assembles a ``ResponseContext`` from the turn's pieces and delegates
the meaning-judgment to an injected ``ResponseJudge``. With a scripted fake judge
the outcome is deterministic, and the assembled context is what the judge sees.
"""

from __future__ import annotations

from bob.application.usecases.decide_response import DecideResponse
from bob.domain.personality.addressivity import Addressivity
from bob.domain.personality.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)
from bob.domain.personality.response_choice import (
    ResponseChoice,
    ResponseContext,
    ResponseIntent,
)


class _FakeJudge:
    """A ResponseJudge that returns a scripted choice and records the context."""

    def __init__(self, choice: ResponseChoice) -> None:
        self._choice = choice
        self.seen: ResponseContext | None = None

    async def decide(self, ctx: ResponseContext) -> ResponseChoice:
        self.seen = ctx
        return self._choice


def _interlocutor() -> Interlocutor:
    return Interlocutor(
        sender_id=7,
        display_name="Боб-старший",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )


async def test_returns_the_judges_choice() -> None:
    expected = ResponseChoice(
        intent=ResponseIntent.REACT, emoji="🔥", reason="warm"
    )
    judge = _FakeJudge(expected)
    use_case = DecideResponse(judge=judge)

    result = await use_case.decide(
        text="огонь идея!",
        interlocutor=_interlocutor(),
        recent_thread="Боб-старший: о\nbob: о",
        mentions_bob=True,
        reply_to_bob=False,
        addressivity=Addressivity.DIRECTED_TO_BOB,
        others_present=False,
        floor_engaged=True,
        mood_tone="excited",
    )

    assert result is expected


async def test_assembles_the_context_from_the_pieces() -> None:
    judge = _FakeJudge(
        ResponseChoice(intent=ResponseIntent.IGNORE, emoji=None, reason="bg")
    )
    use_case = DecideResponse(judge=judge)

    await use_case.decide(
        text="кто-то слышал об этом?",
        interlocutor=_interlocutor(),
        recent_thread="Норман: эй\nbob: да",
        mentions_bob=False,
        reply_to_bob=False,
        addressivity=Addressivity.AMBIENT,
        others_present=True,
        floor_engaged=False,
        mood_tone="neutral",
    )

    ctx = judge.seen
    assert ctx is not None
    assert ctx.text == "кто-то слышал об этом?"
    assert ctx.interlocutor.display_name == "Боб-старший"
    assert ctx.recent_thread == "Норман: эй\nbob: да"
    assert ctx.addressivity is Addressivity.AMBIENT
    assert ctx.others_present is True
    assert ctx.floor_engaged is False
    assert ctx.mood_tone == "neutral"
