# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app
# beadloom:layer=application

"""EndorsementSeeder — warm-start a guest the owner vouched for (BOB-066 Срез W.4).

The application bridge for «кредит доверия по рекомендации owner» (Пласт 4): on the FIRST
contact of a GUEST, if the owner's own recent turns in the shared thread vouch for THIS
sender by name, Bob meets them with a warm :func:`~bob.social.relationship.endorsed_seed`
instead of a blank neutral read (a credit of trust the owner extends on their behalf; the
ordinary drift-to-neutral dissolves it if the guest's own behaviour doesn't confirm it).

The owner's turns are recovered from the SHARED group thread by the configured
``owner_id`` (:func:`~bob.conversation.thread._user_turns` filters the interleaved thread to
one author BY ID — robust to homonyms / renames), so a warm word from another member never
warm-starts anyone. The verdict itself is the pure
:func:`~bob.social.endorsement.endorsement_seed`; this collaborator only sources the owner
turns and gates on GUEST-ness. Built ONLY when ``presence.endorsement`` is on — unwired (the
default) HandleMessage keeps the neutral first-contact path, byte-identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.conversation.thread import _user_turns
from bob.kernel.interlocutor import Trust
from bob.social.endorsement import endorsement_seed

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.kernel.interlocutor import Interlocutor
    from bob.kernel.relationship import Relationship


class EndorsementSeeder:
    """Seed a first-contact guest's relationship warm on an owner endorsement (BOB-066 W.4)."""

    def __init__(self, *, owner_id: int | None) -> None:
        self._owner_id = owner_id

    def seed(
        self,
        interlocutor: Interlocutor | None,
        relationship: Relationship | None,
        history: Sequence[Mapping[str, object]],
    ) -> Relationship | None:
        """Return the warm seed for an endorsed first-contact guest, else ``relationship``.

        Gated on GUEST-ness (an owner / known peer is never seeded — the credit is for a
        newcomer) and on a resolved ``owner_id`` (without it the shared thread cannot be
        narrowed to the owner's OWN turns, so no endorsement is attributed — conservative).
        Otherwise the pure :func:`~bob.social.endorsement.endorsement_seed` decides: a warm
        :func:`~bob.social.relationship.endorsed_seed` only on a genuine first contact
        (``relationship is None``) the owner vouched for by name, else the input relationship
        verbatim. Pure-ish: reads only its arguments, no I/O.
        """
        if (
            interlocutor is None
            or interlocutor.trust is not Trust.GUEST
            or self._owner_id is None
        ):
            return relationship
        owner_texts = _user_turns(history, self._owner_id)
        return endorsement_seed(
            relationship,
            sender_id=interlocutor.sender_id,
            sender_name=interlocutor.display_name,
            owner_texts=owner_texts,
        )
