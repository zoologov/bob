# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Roster-recall acceptance harness for the BDD layer (BOB-080).

Drives Bob's «состав комнаты» recall through REAL boundaries — no private-state peeking:

1. each recent joiner is persisted with the REAL
   :class:`~bob.social.adapters.first_impression_store.SqliteFirstImpressionStore` over a
   REAL SQLite memory store (one ``first_impression`` row per ``sender_id``, with a
   ``first_seen_at`` some days back and the person's ``display_name``);
2. the REAL :class:`~bob.social.usecases.roster_recall.RosterRecall` reads that store's
   recency, builds the roster through the REAL pure core, and applies the ambient-window
   + privacy policies — so the roster must EARN its place by carrying a fresh joiner and
   by the viewer being trusted; nothing is hand-fed;
3. the REAL :func:`~bob.personality.voice.roster_directive` renders the multi-person voice
   line that folds into Bob's compose prompt.

The scenarios then witness Bob's OBSERVABLE recall at the composed-directive boundary —
which people the roster line names, which of them Bob holds as fresh newcomers, and
whether any line is folded at all — never the store's or use-case's internals. Crucially,
:func:`compose_roster_line` takes the incoming social question ONLY to prove INV-2: the
roster is driven by the ambient window, not by a lexical match on that text (the text is
never passed into the recall path).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.kernel.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.personality.voice import roster_directive
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.first_impression import FirstImpression
from bob.social.usecases.roster_recall import RosterRecall

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# A frozen "now" the scenarios reckon recency against; the joiners are seeded relative
# to it so "recent" vs "old-timer" is purely a function of days-ago (INV-3).
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
NEWCOMER_DAYS = 7.0
_LIMIT = 6

_OWNER_ID = 1
_BOB_ID = 2

_VIEWERS: dict[str, Interlocutor] = {
    "owner": Interlocutor(
        sender_id=_OWNER_ID,
        display_name="Владимир",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    ),
    "guest": Interlocutor(
        sender_id=999,
        display_name="Незнакомец",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
    ),
}


@dataclass(frozen=True, slots=True)
class Joiner:
    """One person seeded into the room's first-impression history for a scenario."""

    sender_id: int
    name: str
    days_ago: float


@dataclass(slots=True)
class RosterOutcome:
    """What Bob would OBSERVABLY recall about the room this turn.

    ``directive`` — the composed multi-person voice line (empty when no line is folded);
    ``named`` — the people that line calls out, in order; ``newcomers`` — those the roster
    holds as fresh joiners; ``present`` — whether any roster line is folded at all.
    """

    directive: str = ""
    named: tuple[str, ...] = ()
    newcomers: tuple[str, ...] = ()
    present: bool = False


async def compose_roster_line(
    tmp_path: Path,
    *,
    joined: Sequence[Joiner],
    viewer: str,
    incoming_text: str = "",
) -> RosterOutcome:
    """Seed ``joined``, then recall+compose the roster line for ``viewer`` at ``NOW``.

    Every joiner is written first with the real first-impression store; the real
    RosterRecall then reads recency, builds the roster and applies the ambient-window +
    privacy policies; the real voice directive renders the line. ``incoming_text`` is
    accepted but deliberately NEVER handed to the recall path — it exists only so a
    scenario can prove the recall is ambient, not lexical (INV-2). Returns the observable
    directive framing.
    """
    _ = incoming_text  # INV-2: the recall is ambient — the text is never consulted.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        store = SqliteFirstImpressionStore(repo)
        for person in joined:
            await store.save(
                FirstImpression(
                    sender_id=person.sender_id,
                    first_seen_at=NOW - timedelta(days=person.days_ago),
                    note=f"{person.name} — кто-то из знакомых, уже виделись.",
                    display_name=person.name,
                )
            )
        recall = RosterRecall(
            store=store,
            newcomer_days=NEWCOMER_DAYS,
            limit=_LIMIT,
            owner_id=_OWNER_ID,
            bob_id_source=lambda: _BOB_ID,
        )
        roster = await recall.recent_roster(NOW, viewer=_VIEWERS[viewer])
    finally:
        await repo.close()

    return RosterOutcome(
        directive=roster_directive(roster),
        named=tuple(member.name for member in roster),
        newcomers=tuple(member.name for member in roster if member.is_newcomer),
        present=bool(roster),
    )
