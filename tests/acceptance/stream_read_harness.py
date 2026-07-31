# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Holistic stream-read WIRING harness for the BDD acceptance layer (BOB-072).

Drives the REAL intake seam (:class:`~bob.application.runtime.intake.dispatcher.ChatDispatcher`
+ the REAL focus predicate + the REAL queue-level ``coalesce_stale``) with a FAKE batch reader
whose per-message decision is SCRIPTED per scenario (the LLM's semantic judgement stands in), and
a scripted handler that ACTS on each turn's outcome exactly as the turn gate will:

* a focal message (a direct address — no batch reading rides its scope) → a deterministic REPLY
  (INV-1, the focal guarantee);
* an ambient message → the pure
  :func:`~bob.conversation.room_verdict.decide_from_reading` projects its supplied reading to a
  verdict: REPLY → a reply, REACT → a like, IGNORE → silence;
* EVERY handled message — reply / like / silent alike — is recorded as PERSISTED (INV-S2: Bob
  reads the room but the thread stays whole).

So the scenarios witness Bob's HUMAN, un-scripted choice through the boundary — which messages
earned a word, which a like, which only silence — and that nothing fell out of memory — without
booting the LLM graph (mirroring ``series_budget_harness`` for the batch стрим-read path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake import ChatDispatcher, make_focus_predicate
from bob.conversation.room_reading import ReflectiveIntent, RoomMood, RoomReading
from bob.conversation.room_verdict import VerdictKind, decide_from_reading

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.runtime.intake.scope import TurnScope

# The chat + Bob identity the harness drives; an @mention of BOB_ID reads focused (INV-1).
CHAT_ID = 42
BOB_ID = 500


@dataclass(slots=True)
class StreamObservations:
    """What the acceptance steps witness through the boundary for a settled burst.

    ``replies`` / ``likes`` are the message_ids Bob answered / reacted to; ``persisted`` is
    EVERY message that reached the handler (INV-S2 — читаю комнату, но помню разговор).
    """

    replies: list[int] = field(default_factory=list)
    likes: list[int] = field(default_factory=list)
    persisted: list[int] = field(default_factory=list)

    @property
    def silent(self) -> list[int]:
        """Messages Bob consciously stayed silent on (persisted, но ни ответа, ни лайка)."""
        answered = set(self.replies) | set(self.likes)
        return [message_id for message_id in self.persisted if message_id not in answered]


@dataclass(frozen=True, slots=True)
class BurstMessage:
    """One scripted inbound: id, sender, text, whether it directly addresses Bob, its reading.

    ``reading`` is the per-message verdict the FAKE batch reader returns for an ambient message
    (the LLM's semantic choice, scripted). It is ignored for a focal message (``mentions_bob``),
    which takes the deterministic reply path above the batch.
    """

    message_id: int
    sender_id: int
    text: str
    mentions_bob: bool
    reading: RoomReading


def _reading(intent: ReflectiveIntent, *, emoji: str | None = None) -> RoomReading:
    """A per-message reading carrying an above-floor salience (the batch already chose)."""
    return RoomReading(
        situation="",
        pairings=(),
        room_mood=RoomMood.WARM,
        intent=intent,
        addressee_id=None,
        salience=0.9,
        emoji=emoji,
        wants_web=False,
        reason="scripted",
    )


def reply_reading() -> RoomReading:
    """The reader's verdict for a message worth a word (a real question / a point to Bob)."""
    return _reading(ReflectiveIntent.REPLY)


def react_reading(emoji: str = "🔥") -> RoomReading:
    """The reader's verdict for a message worth a like (a good line, not worth words)."""
    return _reading(ReflectiveIntent.REACT, emoji=emoji)


def ignore_reading() -> RoomReading:
    """The reader's verdict for chatter Bob consciously passes on (cross-talk / «ок»)."""
    return _reading(ReflectiveIntent.IGNORE)


class _ScriptedBatchReader:
    """A fake ambient batch reader: returns each kept message's scripted per-message reading."""

    def __init__(self, by_id: dict[int, RoomReading]) -> None:
        self._by_id = by_id

    async def read(self, messages: Sequence[MessageReceived]) -> Sequence[RoomReading]:
        return [self._by_id[message.message_id] for message in messages]


def _event(spec: BurstMessage) -> MessageReceived:
    return MessageReceived(
        update_id=spec.message_id,
        chat_id=CHAT_ID,
        message_id=spec.message_id,
        text=spec.text,
        sender_id=spec.sender_id,
        sender_name=f"u{spec.sender_id}",
        mentions_bob=spec.mentions_bob,
    )


async def drive_stream(
    *, specs: Sequence[BurstMessage], stale_coalesce: bool = False
) -> StreamObservations:
    """Drive one settled ambient/focal burst through the real dispatcher; witness the outcome.

    The FAKE batch reader supplies each ambient message's scripted reading; the handler applies
    the pure verdict (or a deterministic reply for a focal message) and records every persisted
    message. Returns the observable tally the steps assert.
    """
    observations = StreamObservations()

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        # Every handled message is persisted — INV-S2 (thread stays whole).
        observations.persisted.append(message.message_id)
        reading = scope.ambient_reading
        if reading is None:
            # Focal (direct address): deterministic reply — INV-1.
            observations.replies.append(message.message_id)
            return
        verdict = decide_from_reading(reading)
        if verdict.kind is VerdictKind.REPLY:
            observations.replies.append(message.message_id)
        elif verdict.kind is VerdictKind.REACT:
            observations.likes.append(message.message_id)

    reader = _ScriptedBatchReader({
        spec.message_id: spec.reading for spec in specs if not spec.mentions_bob
    })
    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=make_focus_predicate(lambda: BOB_ID),
        ambient_batch=reader,
        stale_coalesce_enabled=stale_coalesce,
    )
    for spec in specs:
        dispatcher.submit(_event(spec))
    await dispatcher.aclose()
    return observations


# --- Scenario burst factories ----------------------------------------------------------


def burst_chatter_with_one_question_and_a_joke() -> list[BurstMessage]:
    """Two people chat weather, one asks Bob a question (no «Боб,»), one drops a good joke, «ок».

    The batch read chooses by MEANING: reply to the question, like the joke, pass on the weather
    chatter and the empty «ок». Not «answer the first», not «answer all».
    """
    return [
        BurstMessage(1, 11, "сегодня льёт весь день", False, ignore_reading()),
        BurstMessage(2, 12, "ага, промок пока шёл", False, ignore_reading()),
        BurstMessage(3, 11, "а как вообще зонды на Луне садятся?", False, reply_reading()),
        BurstMessage(4, 12, "у меня зонт вывернуло, комедия просто", False, react_reading()),
        BurstMessage(5, 11, "ок", False, ignore_reading()),
    ]


def burst_with_a_direct_address() -> list[BurstMessage]:
    """A burst of ambient chatter the read would pass on, with ONE direct @-address to Bob.

    Every ambient reading is IGNORE, so ONLY the focal guarantee can produce a reply — pinning
    that a direct address is never silenced by the batch semantics (INV-1).
    """
    return [
        BurstMessage(1, 11, "болтаем про своё", False, ignore_reading()),
        BurstMessage(2, 12, "Bob, глянь что с зондом?", True, ignore_reading()),
        BurstMessage(3, 11, "и дальше про своё", False, ignore_reading()),
    ]


def burst_cross_talk_between_two() -> list[BurstMessage]:
    """Norman and Lyosha talk to each other, not to Bob — the read passes on all of it.

    Bob stays silent (не влезает), but every line is persisted (он помнит разговор) — INV-S2.
    """
    return [
        BurstMessage(1, 11, "Лёш, ты дочинил ровер?", False, ignore_reading()),
        BurstMessage(2, 12, "почти, осталась подвеска", False, ignore_reading()),
        BurstMessage(3, 11, "о, красава", False, ignore_reading()),
    ]


def burst_with_a_superseded_reformulation() -> list[BurstMessage]:
    """The same sender re-asks in the very next slot; another sender adds a line worth a word.

    With stale-coalesce ON the overtaken FIRST line is dropped from the read (never answered —
    INV-S3) yet still persisted (INV-S2); the sender's latest form and the other line are read.
    """
    return [
        BurstMessage(1, 11, "а что там по погоде… нет, погоди", False, ignore_reading()),
        BurstMessage(2, 11, "короче, дождь до вечера будет?", False, ignore_reading()),
        BurstMessage(3, 12, "кстати, зонды правда сами садятся?", False, reply_reading()),
    ]
