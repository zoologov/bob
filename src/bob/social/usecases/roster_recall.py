# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""RosterRecall — the ambient «состав комнаты» recall use-case (BOB-080).

The application seam that decides WHEN and TO WHOM Bob recalls who lately turned up in
the room, wrapping the pure :func:`~bob.social.roster.build_roster` core with the three
policies that keep the recall human (not a script) and safe:

* **AMBIENT WINDOW (INV-4).** A roster surfaces ONLY while it carries at least one fresh
  newcomer (someone met within ``newcomer_days``) — the way a person keeps recent faces
  «in his head» a few days and lets them fade. No recent joiners → an empty roster → no
  prompt line → no flood.
* **PRIVACY.** Only an OWNER / KNOWN viewer is handed the room's rundown; a GUEST (a
  stranger) is not given a list of everyone present. This reads authz-kind but changes
  no access policy (a guest still gets his full social reply).
* **BEST-EFFORT.** The store read is wrapped — a flaky recency read yields an empty
  roster and logs, never breaking a turn that must still reply (lesson BOB-078 Part D).

The ``social.roster`` flag is gated in the composition root (the use-case is built only
when on; :class:`~bob.social.usecases.social_context.SocialContext` tolerates its
absence). It reads the recency of accumulated impressions only — it never writes — and
excludes the owner + Bob himself (known, not newcomers) from the roster. Its window /
cap thresholds (``newcomer_days`` / ``limit``) are injected as plain values, so this
social use-case stays free of any composition-root config type.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.social.interlocutor import InterlocutorKind
from bob.social.roster import build_roster

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from bob.social.first_impression import FirstImpression
    from bob.social.interlocutor import Interlocutor
    from bob.social.roster import RosterMember

logger = logging.getLogger(__name__)

__all__ = ["RosterRecall"]

# Who is trusted enough to receive the room's rundown — the owner and known friends;
# a guest (or a bot) is not handed a list of everyone present (privacy, not authz).
_ROSTER_VIEWERS = frozenset({InterlocutorKind.OWNER, InterlocutorKind.KNOWN})


class _RecencyReader(Protocol):
    """The narrow recency read RosterRecall needs (a slice of ``FirstImpressionStore``)."""

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        """Return the ``limit`` most-recently-met impressions, newest first."""
        ...


class RosterRecall:
    """Recall who lately turned up — behind the ambient window + privacy + best-effort."""

    def __init__(
        self,
        *,
        store: _RecencyReader,
        newcomer_days: float,
        limit: int,
        owner_id: int,
        bob_id_source: Callable[[], int | None] | None = None,
    ) -> None:
        self._store = store
        self._newcomer_days = newcomer_days
        self._limit = limit
        self._owner_id = owner_id
        self._bob_id_source = bob_id_source

    async def recent_roster(
        self, now: datetime, *, viewer: Interlocutor | None
    ) -> tuple[RosterMember, ...]:
        """Recall the roster of recent joiners for ``viewer`` at ``now``, or empty.

        Empty (no line) unless ALL hold: ``viewer`` is an OWNER / KNOWN person (privacy)
        and the built roster carries at least one fresh newcomer (the ambient window,
        INV-4). The owner + Bob himself are excluded (known, not newcomers). Best-effort:
        a flaky recency read yields an empty roster and logs, never breaking the turn.
        """
        if viewer is None or viewer.kind not in _ROSTER_VIEWERS:
            return ()
        try:
            impressions = await self._store.recent(limit=self._limit)
        except Exception:
            logger.exception("recalling roster failed (ignored)")
            return ()
        roster = build_roster(
            impressions,
            now,
            newcomer_days=self._newcomer_days,
            exclude_ids=self._exclude_ids(),
            limit=self._limit,
        )
        # Ambient window (INV-4): hold the roster in mind only while a fresh joiner is on
        # it; a roster of only old-timers fades to nothing (no line, no flood).
        if not any(member.is_newcomer for member in roster):
            return ()
        return roster

    def _exclude_ids(self) -> frozenset[int]:
        """The ids kept OFF the roster: the owner and (once resolved) Bob himself."""
        excluded = {self._owner_id}
        bob_id = self._bob_id_source() if self._bob_id_source is not None else None
        if bob_id is not None:
            excluded.add(bob_id)
        return frozenset(excluded)
