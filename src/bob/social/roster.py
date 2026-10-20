# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Roster — the pure «состав комнаты» core Bob recalls by social occasion (BOB-080).

Bob keeps recent acquaintances "in his head" the way a person does — able to NAME who
lately turned up in the room, telling newcomers (by time) from old-timers. This module
is the deterministic, I/O-free heart of that:

* :class:`~bob.kernel.roster.RosterMember` — one named person on the roster: who
  (``sender_id``), their ``name``, WHEN Bob first met them, and whether they are a
  ``is_newcomer`` (fresh). The value lives in the shared kernel (BOB-113, RFC D);
  the behaviour that builds a roster stays here.
* :func:`is_newcomer` — strictly time-based (INV-3): someone is "new" purely because
  Bob met them within ``newcomer_days`` — never by authz-kind. Tolerant of a legacy
  naive stamp (read as UTC) so it never raises on the subtraction.
* :func:`build_roster` — folds the accumulated first impressions into a roster: drops
  excluded ids (owner / Bob himself), marks each newcomer, resolves a name
  (``display_name`` or parsed from the note), sorts most-recent-first, and caps the
  count. Deterministic order, no I/O, ``now`` is a parameter (no clock of its own).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.kernel.roster import RosterMember

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.social.first_impression import FirstImpression

__all__ = ["build_roster", "is_newcomer", "member_name"]

# The note is written as ``"{name} — …"`` (impression_note_for), so a legacy row with
# no display_name yields the name as the head of the note before this separator.
_NAME_SEPARATOR = " — "


def _as_aware(moment: datetime) -> datetime:
    """Return ``moment`` as a tz-aware instant (a naive legacy stamp is read as UTC)."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def is_newcomer(first_seen: datetime, now: datetime, *, newcomer_days: float) -> bool:
    """Whether someone met at ``first_seen`` is still a NEWCOMER at ``now`` (by time).

    Strictly time-based (INV-3): a person is new purely because Bob met them within
    ``newcomer_days`` — the boundary is inclusive (exactly ``newcomer_days`` old still
    counts). Both instants are normalised to tz-aware UTC first, so a legacy naive
    ``first_seen`` never raises on the subtraction.
    """
    return _as_aware(now) - _as_aware(first_seen) <= timedelta(days=newcomer_days)


def member_name(impression: FirstImpression) -> str:
    """Resolve a person's display name from their impression (pure fallback).

    Prefers the first-class ``display_name``; for a legacy row that lacks it, the name
    is the head of the ``"{name} — …"`` note before the separator.
    """
    if impression.display_name:
        return impression.display_name
    return impression.note.split(_NAME_SEPARATOR, 1)[0].strip()


def build_roster(
    impressions: Sequence[FirstImpression],
    now: datetime,
    *,
    newcomer_days: float,
    exclude_ids: frozenset[int],
    limit: int,
) -> tuple[RosterMember, ...]:
    """Build the room roster from accumulated first impressions (deterministic, pure).

    Drops ``exclude_ids`` (owner / Bob himself — known, not "newcomers"), marks each
    person a newcomer by time, resolves a name (``display_name`` or parsed from the
    note), sorts most-recently-met first, and returns at most ``limit`` members. No
    I/O; the roster is built ONLY from the real impressions passed in (INV-1).
    """
    members = [
        RosterMember(
            sender_id=impression.sender_id,
            name=member_name(impression),
            first_seen_at=impression.first_seen_at,
            is_newcomer=is_newcomer(
                impression.first_seen_at, now, newcomer_days=newcomer_days
            ),
        )
        for impression in impressions
        if impression.sender_id not in exclude_ids
    ]
    members.sort(key=lambda member: _as_aware(member.first_seen_at), reverse=True)
    return tuple(members[:limit])
