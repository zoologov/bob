# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for StalenessReassessor — the application collaborator over the staleness gate.

It reads what landed during generation (a non-draining ``peek_since`` of the intake
buffer, passed in), maps each :class:`MessageReceived` to the presence domain's
value-shaped :class:`ArrivedMessage`, consults the semantic judge ONLY when something
landed, and returns the pure gate's outcome. These tests pin the mapping (reply-to-Bob
and same-author detection) and the two structural rails (empty burst / no-judge).
"""

from __future__ import annotations

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.staleness_reassessor import StalenessReassessor
from bob.presence.staleness import (
    StalenessContext,
    StalenessGate,
    StalenessOutcome,
    StalenessReading,
)

_BOB_USER_ID = 100
_AUTHOR_ID = 7


class _FakeJudge:
    """Records the context it was asked to read and returns a fixed reading."""

    def __init__(self, reading: StalenessReading) -> None:
        self._reading = reading
        self.seen: StalenessContext | None = None

    async def assess(self, ctx: StalenessContext) -> StalenessReading:
        self.seen = ctx
        return self._reading


def _reading(**flags: bool) -> StalenessReading:
    base = {
        "answered_by_other": False,
        "topic_closed": False,
        "same_author_clarified": False,
        "new_direct_question": False,
    }
    base.update(flags)
    return StalenessReading(reason="fake", **base)


def _message(
    *,
    update_id: int,
    sender_id: int | None = _AUTHOR_ID,
    reply_to_sender_id: int | None = None,
    mentions_bob: bool = False,
    text: str = "текст",
) -> MessageReceived:
    return MessageReceived(
        update_id=update_id,
        chat_id=1,
        message_id=update_id,
        text=text,
        sender_id=sender_id,
        reply_to_sender_id=reply_to_sender_id,
        mentions_bob=mentions_bob,
    )


def _reassessor(judge: _FakeJudge) -> StalenessReassessor:
    return StalenessReassessor(judge, StalenessGate())


async def test_empty_burst_sends_without_consulting_the_judge() -> None:
    # Arrange: nothing landed during generation.
    judge = _FakeJudge(_reading(answered_by_other=True))
    reassessor = _reassessor(judge)

    # Act
    outcome = await reassessor.reassess(
        drafted="черновик",
        newly_arrived=(),
        draft_author_sender_id=_AUTHOR_ID,
        bob_user_id=_BOB_USER_ID,
    )

    # Assert: structural short-circuit — SEND, and the judge is never called.
    assert outcome is StalenessOutcome.SEND
    assert judge.seen is None


async def test_shifted_context_delegates_to_the_judge_and_gate() -> None:
    # Arrange: someone else answered while Bob drafted.
    judge = _FakeJudge(_reading(answered_by_other=True))
    reassessor = _reassessor(judge)

    # Act
    outcome = await reassessor.reassess(
        drafted="черновик",
        newly_arrived=(_message(update_id=5, sender_id=9),),
        draft_author_sender_id=_AUTHOR_ID,
        bob_user_id=_BOB_USER_ID,
    )

    # Assert: the judge read the draft + arrival, the gate mapped it → DROP_TO_LIKE.
    assert outcome is StalenessOutcome.DROP_TO_LIKE
    assert judge.seen is not None
    assert judge.seen.drafted == "черновик"


async def test_maps_reply_to_bob_and_same_author_signals() -> None:
    # Arrange: the arrival is the draft's author replying to Bob (a clarification shape).
    judge = _FakeJudge(_reading())
    reassessor = _reassessor(judge)

    # Act
    await reassessor.reassess(
        drafted="черновик",
        newly_arrived=(
            _message(
                update_id=5,
                sender_id=_AUTHOR_ID,
                reply_to_sender_id=_BOB_USER_ID,
                mentions_bob=True,
            ),
        ),
        draft_author_sender_id=_AUTHOR_ID,
        bob_user_id=_BOB_USER_ID,
    )

    # Assert: the value-shaped ArrivedMessage carries the derived flags.
    assert judge.seen is not None
    arrived = judge.seen.newly_arrived[0]
    assert arrived.reply_to_bob is True
    assert arrived.from_draft_author is True
    assert arrived.mentions_bob is True


async def test_reply_to_someone_else_is_not_reply_to_bob() -> None:
    # Arrange: the arrival replies to another guest, not Bob, from a different author.
    judge = _FakeJudge(_reading())
    reassessor = _reassessor(judge)

    # Act
    await reassessor.reassess(
        drafted="черновик",
        newly_arrived=(
            _message(update_id=5, sender_id=9, reply_to_sender_id=42),
        ),
        draft_author_sender_id=_AUTHOR_ID,
        bob_user_id=_BOB_USER_ID,
    )

    # Assert: neither reply-to-Bob nor same-author holds.
    assert judge.seen is not None
    arrived = judge.seen.newly_arrived[0]
    assert arrived.reply_to_bob is False
    assert arrived.from_draft_author is False
