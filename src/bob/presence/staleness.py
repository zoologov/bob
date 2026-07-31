# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=domain

"""StalenessGate — reassess a drafted reply against the context that shifted (BOB-066 3.1).

A real participant does not fire a reply he wrote thirty seconds ago into a room that
has since moved on. While Bob was drafting, other messages may have landed: someone
else may have answered the very point he was making, the thread may have closed, the
asker may have refined the question, or a fresh direct question may have arrived on
top. This module holds the ONE pure decision that turns "what landed during
generation" into an outcome for the drafted reply:

* :data:`~StalenessOutcome.SEND` — nothing relevant shifted; send the draft as-is.
* :data:`~StalenessOutcome.REWRITE` — the asker clarified/corrected; regenerate.
* :data:`~StalenessOutcome.DROP_TO_LIKE` — the reply is now redundant (answered by
  someone else / topic closed); react instead of speaking a stale line.
* :data:`~StalenessOutcome.MERGE` — a fresh direct question landed; fold both into
  ONE reply (dedup — never two replies for one exchange).

🔴 **B2 = B7 (one primitive).** Reassessing AFTER generation (post-draft) and being
interrupted MID-generation are the same act — "reassess the drafted answer against
the shifted context" — so both ride this single gate.

Following the epic's load-bearing principle (``LLM verbalises → pure core decides``),
the semantic read of the shift is VERBALISED by a judge (:class:`StalenessReading`,
produced through the :class:`~bob.presence.ports.StalenessJudge` port) and this pure,
deterministic core (:func:`decide_staleness`) DECIDES the outcome — exactly as
:func:`~bob.conversation.room_verdict.decide_from_reading` does. No I/O, no clock, no
rng: the verdict is pinned by unit tests and hardened by mutation. The
:class:`StalenessGate` facade wraps it with the cheap structural short-circuit
(nothing landed → SEND) and a fail-safe (no reading → SEND, never a silent drop).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ArrivedMessage",
    "QueuedAmbient",
    "StalenessContext",
    "StalenessGate",
    "StalenessOutcome",
    "StalenessReading",
    "coalesce_stale",
    "decide_staleness",
    "nothing_arrived",
]


@dataclass(frozen=True, slots=True)
class QueuedAmbient:
    """One buffered ambient message, as value primitives, for queue-level coalescing.

    Carried BY VALUE (not the runtime ``MessageReceived``) so the presence domain stays free
    of application/transport imports. ``sender_id`` attributes the line (``None`` when the
    sender is not identifiable); ``is_focal`` marks a direct address to Bob — never dropped
    (INV-1). Ambient bursts reach :func:`coalesce_stale` with ``is_focal`` False (the focal
    part is split off upstream); the flag is a defensive rail so the core never drops a focal.
    """

    sender_id: int | None
    is_focal: bool = False


def coalesce_stale(batch: Sequence[QueuedAmbient]) -> tuple[bool, ...]:
    """Per ambient message, whether to KEEP it for the read (``True``) or treat it as
    superseded (``False``) — pure, deterministic, mutation-pinned.

    Staying-in-the-present (INV-S3) at the QUEUE level, before the holistic stream-read: a
    message is superseded ONLY when the SAME identified sender speaks again in the very next
    slot of the burst — a re-ask / reformulation the stream has already overtaken, so Bob
    answers the latest form, not the stale one. The rule is deliberately conservative
    (liveness > economy):

    * 🔴 **Focal is never superseded** (``is_focal`` → always kept), reconciling the drop with
      INV-1 — a direct address is a guarantee.
    * An **unidentified** sender (``sender_id`` is ``None``) is never coalesced — two anonymous
      lines are not provably the "same sender".
    * A message with **another sender interposed** before the same sender speaks again is KEPT
      (the topic may have branched — do not cut live context).

    A superseded message is only dropped from the READ; the caller still persists and
    floor-advances it (INV-S2) — the thread stays intact, Bob just does not reply to it.
    """
    keep: list[bool] = []
    last = len(batch) - 1
    for index, message in enumerate(batch):
        if message.is_focal or message.sender_id is None or index == last:
            keep.append(True)
            continue
        nxt = batch[index + 1]
        superseded = not nxt.is_focal and nxt.sender_id == message.sender_id
        keep.append(not superseded)
    return tuple(keep)


class StalenessOutcome(StrEnum):
    """What Bob does with a drafted reply once the room has shifted under it.

    * :data:`SEND` — the draft is still fresh; deliver it unchanged.
    * :data:`REWRITE` — regenerate the reply against a same-author clarification.
    * :data:`DROP_TO_LIKE` — the reply is now redundant; set a reaction instead.
    * :data:`MERGE` — fold a fresh direct question into one deduplicated reply.
    """

    SEND = "send"
    REWRITE = "rewrite"
    DROP_TO_LIKE = "drop_to_like"
    MERGE = "merge"


@dataclass(frozen=True, slots=True)
class ArrivedMessage:
    """One message that landed while Bob was drafting, as value primitives.

    Carried BY VALUE (not the runtime ``MessageReceived``) so the presence domain stays
    free of application/transport imports. ``from_draft_author`` marks a message from the
    same person Bob is drafting a reply to (a candidate clarification); ``reply_to_bob``
    and ``mentions_bob`` mark a fresh direct address that may deserve a merge.
    """

    sender_id: int | None
    text: str
    mentions_bob: bool
    reply_to_bob: bool
    from_draft_author: bool


@dataclass(frozen=True, slots=True)
class StalenessContext:
    """The INPUT a :class:`~bob.presence.ports.StalenessJudge` reads to verbalise the shift.

    ``drafted`` is the reply Bob composed this turn; ``newly_arrived`` is what landed in
    arrival order while he was composing it (a non-draining peek of the intake buffer).
    """

    drafted: str
    newly_arrived: tuple[ArrivedMessage, ...]


@dataclass(frozen=True, slots=True)
class StalenessReading:
    """The judge's VERBALISATION of how the context shifted under the draft.

    Every field is a signal the pure core weighs; none is the outcome. ``reason`` is for
    logs only, never shown to the user.
    """

    answered_by_other: bool
    topic_closed: bool
    same_author_clarified: bool
    new_direct_question: bool
    reason: str


def nothing_arrived(newly_arrived: tuple[ArrivedMessage, ...]) -> bool:
    """Whether nothing landed during generation — the cheap structural "still fresh" check."""
    return len(newly_arrived) == 0


def decide_staleness(reading: StalenessReading) -> StalenessOutcome:
    """Map a :class:`StalenessReading` to a :class:`StalenessOutcome` — pure, deterministic.

    Precedence is deliberate and mutation-pinned:

    1. 🔴🔴 **Fresh direct question** (``new_direct_question``) → :data:`MERGE`. This is
       checked FIRST so that a message carrying a fresh DIRECT question (a focal signal) is
       NEVER dropped to a like — even when the original point was answered by someone else or
       the topic closed. It reconciles INV-1 (the focal guarantee) with the redundancy drop:
       one reply covers both the original and the new question (dedup), so the new question is
       always answered, never silenced to a reaction.
    2. **Redundant** (``answered_by_other`` or ``topic_closed``) → :data:`DROP_TO_LIKE`.
       With no fresh direct question in play, a moot draft is dropped to a reaction — there is
       no point rewriting a reply the room no longer needs.
    3. **Same-author clarification** (``same_author_clarified``) → :data:`REWRITE`.
    4. Otherwise → :data:`SEND` (the draft is still fresh).
    """
    if reading.new_direct_question:
        return StalenessOutcome.MERGE
    if reading.answered_by_other or reading.topic_closed:
        return StalenessOutcome.DROP_TO_LIKE
    if reading.same_author_clarified:
        return StalenessOutcome.REWRITE
    return StalenessOutcome.SEND


@dataclass(frozen=True, slots=True)
class StalenessGate:
    """Pure facade: a drafted reply + what landed during generation → an outcome.

    Wraps :func:`decide_staleness` with the two structural rails that keep the gate
    honest without a judge call: an empty burst is always fresh (SEND), and a missing
    reading fails safe to SEND — Bob never silently drops a reply he drafted.
    """

    def reassess(
        self,
        newly_arrived: tuple[ArrivedMessage, ...],
        reading: StalenessReading | None,
    ) -> StalenessOutcome:
        """Return the outcome for the draft given what landed and the judge's read.

        Nothing landed → :data:`~StalenessOutcome.SEND` (no judge needed). Something
        landed but no reading (judge unavailable/failed) → :data:`~StalenessOutcome.SEND`
        (fail-safe). Otherwise delegate to :func:`decide_staleness`.
        """
        if nothing_arrived(newly_arrived):
            return StalenessOutcome.SEND
        if reading is None:
            return StalenessOutcome.SEND
        return decide_staleness(reading)
