# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""First-impression source adapter — the live seam the compose path reads (BOB-019).

A thin application adapter that keeps :class:`HandleMessage` pure of store/clock
plumbing for Bob's LIGHT per-person first impression:

* :meth:`FirstImpressionTracker.prior_impression` reads any PRIOR impression note
  for the perceived :class:`~bob.social.interlocutor.Interlocutor` (a
  returning sender → his stored note; a new one → ``None``), so the compose path
  can fold "этого человека ты уже видел; впечатление было такое-то" into the prompt.
* :meth:`FirstImpressionTracker.note_first_contact` records a fresh, grounded note
  on FIRST contact (the impression is formed once; a known sender is left untouched
  by the store's DO-NOTHING save), stamping ``first_seen_at`` from the injected
  :class:`~bob.kernel.ports.Clock`.

It is grounded: the note is derived by the pure
:func:`~bob.social.first_impression.impression_note_for` from who Bob can
already see the sender is — no fabricated facts. A sender with no id (``sender_id is
None``) cannot be keyed or recognised, so both operations are clean no-ops for them.
This is per-PERSON data (about THEM), NOT owner-private memory — safe even for a guest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.social.first_impression import (
    FirstImpression,
    impression_note_for,
)

if TYPE_CHECKING:
    from bob.kernel.ports import Clock
    from bob.social.interlocutor import Interlocutor
    from bob.social.ports import FirstImpressionStore


class FirstImpressionTracker:
    """Read a prior first-impression note + record one on first contact (per sender)."""

    def __init__(self, *, store: FirstImpressionStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def prior_impression(self, interlocutor: Interlocutor) -> str | None:
        """Return Bob's PRIOR first-impression note for this sender, or ``None``.

        A returning sender (already on record) yields his stored note so the compose
        path can recall him; a new sender — or one with no id — yields ``None`` (no
        recall, he is being met for the first time).
        """
        if interlocutor.sender_id is None:
            return None
        stored = await self._store.load(interlocutor.sender_id)
        return None if stored is None else stored.note

    async def note_first_contact(self, interlocutor: Interlocutor) -> None:
        """Record a fresh, grounded first impression on FIRST contact (per sender).

        Derives a LIGHT note from the interlocutor (grounded — no fabricated facts),
        stamps ``first_seen_at`` from the clock, and persists it. The store keeps the note
        and the first-seen instant as first written, so a returning sender is recognised;
        the ONE thing a later turn refreshes is their ``@ник`` (BOB-090.B3 — a handle
        changes, and everyone Bob already knows has none stored yet). A sender with no id
        is a clean no-op (cannot be keyed or recognised later).
        """
        if interlocutor.sender_id is None:
            return
        impression = FirstImpression(
            sender_id=interlocutor.sender_id,
            first_seen_at=self._clock.now(),
            note=impression_note_for(interlocutor),
            display_name=interlocutor.display_name,
            username=interlocutor.username,
        )
        await self._store.save(impression)
