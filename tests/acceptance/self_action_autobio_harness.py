# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Autobiographical-memory acceptance harness for the BDD layer (BOB-079).

Drives Bob's OWN-DEED read path through REAL boundaries — no private-state peeking:

1. a self-action is written with the REAL
   :class:`~bob.memory.adapters.self_action_recorder.MemoryBackedSelfActionRecorder`
   over a REAL SQLite memory store (``save_episode_entity`` → ``self_action`` episode);
2. a relevant question is answered by the REAL keyword recall
   (:class:`~bob.memory.adapters.fts_recall.Fts5MemoryRecall`), so the deed must earn
   its place in the recall pool by matching the question — nothing is hand-fed;
3. the surfaced pool passes the REAL read gates that guard the reply —
   :func:`~bob.conversation.conversation.recalled_excluding_reflections` (a deed is
   shareable autobiography, NOT a contained reflection) and
   :func:`~bob.social.disclosure.filter_surfaceable` (owner trust);
4. the REAL voice gate (:func:`~bob.personality.voice.recall_has_self_action` +
   :func:`~bob.personality.voice.recalled_self_action_directive`) decides whether the
   first-person OWNERSHIP directive folds into Bob's voice.

The scenarios then witness Bob's OBSERVABLE framing at the composed-reply boundary —
which first-person deed grounds the answer and whether the ownership directive is
active — never the loop's or store's internals. When NO deed was recorded (S4), the
pool carries no self-action, so the directive stays absent: Bob has nothing to own and
cannot confabulate one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.conversation.conversation import recalled_excluding_reflections
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.self_action_recorder import MemoryBackedSelfActionRecorder
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.personality.voice import recall_has_self_action, recalled_self_action_directive
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE, filter_surfaceable
from bob.social.interlocutor import Trust

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from bob.kernel.episode_types import Recalled
    from bob.memory.self_action import SelfAction

_OWNER_ID = 27468732


class _FixedClock:
    """A frozen clock — the write timestamp is irrelevant to the read behaviour."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@dataclass(slots=True)
class OwnershipOutcome:
    """What Bob would OBSERVABLY do with his own recalled deeds this turn.

    ``surfaced`` — the deed contents that passed every read gate and ground the reply;
    ``ownership_directive_active`` — whether the first-person ownership voice line folds
    in; ``directive`` — that line's text (empty when inactive).
    """

    surfaced: tuple[str, ...] = ()
    ownership_directive_active: bool = False
    directive: str = ""


async def recall_own_deeds(
    tmp_path: Path,
    question: str,
    *,
    record: Sequence[SelfAction] = (),
) -> OwnershipOutcome:
    """Record ``record`` deeds, then answer ``question`` through the real read path.

    Every deed is written first-person via the real recorder; the real keyword recall
    then answers ``question`` (the deed must MATCH to surface); the real read gates run;
    the real voice gate decides the ownership directive. Returns the observable framing.
    """
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        recorder = MemoryBackedSelfActionRecorder(
            repo, clock=_FixedClock(datetime(2026, 8, 1, 21, 18, tzinfo=UTC))
        )
        for action in record:
            # Owner-private provenance: these are Bob's own deeds for the owner (INV-1).
            await recorder.record(
                action, sender_id=_OWNER_ID, visibility=VISIBILITY_OWNER_PRIVATE
            )

        raw = await Fts5MemoryRecall(repo).recall(question, k=8)
        # The two READ gates the reply pool passes through, in the same order the app uses:
        # reflections are contained (a deed is NOT a reflection → kept), then owner trust
        # keeps every owner-private item (the owner sees his own autobiography).
        gated: tuple[Recalled, ...] = filter_surfaceable(
            recalled_excluding_reflections(raw), Trust.TRUSTED
        )
    finally:
        await repo.close()

    active = recall_has_self_action(gated)
    return OwnershipOutcome(
        surfaced=tuple(str(item.get("content", "")) for item in gated),
        ownership_directive_active=active,
        directive=recalled_self_action_directive() if active else "",
    )
