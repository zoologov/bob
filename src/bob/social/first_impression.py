# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""FirstImpression — a LIGHT per-person first-impression note (BOB-019).

When someone new writes, Bob forms a quick read on them — recognised vs new — and
keeps a short note he can recall the next time that same person turns up ("кажется,
мы уже сталкивались"). This is the deliberately minimal foundation for the full
multi-party RelationshipTracker (BOB-014), NOT that engine: one short, grounded
line per ``sender_id``, nothing more.

* :class:`FirstImpression` — a frozen value object: WHO (``sender_id``), WHEN Bob
  first met them (``first_seen_at``), and a one-line ``note`` (how he clocked them).
* :func:`impression_note_for` — a pure, cheap heuristic that derives that light
  note from the perceived :class:`~bob.social.interlocutor.Interlocutor`
  (its kind + display name). It is grounded in what Bob can already see — who the
  person is, socially — and invents NO facts about them; it is a *vibe*, not a
  dossier. No I/O, no clock of its own, so it stays trivially testable and pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.social.interlocutor import InterlocutorKind

if TYPE_CHECKING:
    from datetime import datetime

    from bob.social.interlocutor import Interlocutor

__all__ = ["FirstImpression", "impression_note_for"]

# A light, grounded one-liner per kind — a *vibe* Bob can recall, never a fabricated
# fact about the person. ``{name}`` is filled with the sender's display name. Russian
# persona voice (project language); Cyrillic look-alikes intentional in these literals.
_NOTE_BY_KIND: dict[InterlocutorKind, str] = {
    InterlocutorKind.OWNER: "{name} — твой владелец; этого человека ты знаешь.",
    InterlocutorKind.KNOWN: "{name} — кто-то из знакомых, уже виделись.",
    InterlocutorKind.GUEST: (
        "{name} — незнакомец; впечатление пока осторожное."
    ),
    InterlocutorKind.BOT: "{name} — другой бот; держишь это в уме.",
}


@dataclass(frozen=True, slots=True)
class FirstImpression:
    """How Bob first clocked one person: who, when, and a short impression note."""

    sender_id: int
    first_seen_at: datetime
    note: str

    def __post_init__(self) -> None:
        if not self.note.strip():
            raise ValueError("first-impression note must be non-empty")


def impression_note_for(interlocutor: Interlocutor) -> str:
    """Derive a LIGHT, grounded first-impression note from the interlocutor (pure).

    Picks a short one-liner by the sender's social kind (owner / known / guest /
    bot) and folds in their display name — a *vibe* grounded in who Bob can already
    see they are, never an invented fact about them. Deterministic: the same
    interlocutor always yields the same note. Deliberately minimal (this is not the
    RelationshipTracker, BOB-014): one line, no dossier.
    """
    template = _NOTE_BY_KIND[interlocutor.kind]
    return template.format(name=interlocutor.display_name)
