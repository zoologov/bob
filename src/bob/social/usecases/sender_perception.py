# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""SenderPerception — turn an inbound message into an Interlocutor (BOB-019).

The wiring seam that lets Bob *perceive* WHO is writing: it composes the unchanged
access policy (:class:`~bob.social.usecases.authorizer.Authorizer`) with the pure
domain :func:`~bob.social.interlocutor.classify` so a received
:class:`~bob.application.runtime.events.MessageReceived` becomes an
:class:`~bob.social.interlocutor.Interlocutor` (owner / known / guest /
bot + trust). :class:`~bob.application.usecases.handle_message.HandleMessage` folds
that identity into Bob's voice.

This is perception, NOT a gate: it reads ``is_owner`` (identity, not chat-scoped,
so Bob recognises his owner everywhere) and ``is_authorized`` (the full
chat-scoped policy) but changes no access decision and does not alter which
pipeline runs — the guest-restricted path is a later bead. ``is_bot`` defaults
False (the event carries no bot flag yet); the model already covers bots for when
a transport supplies it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from bob.social.gender import Gender
from bob.social.interlocutor import Interlocutor, classify

if TYPE_CHECKING:
    from bob.application.runtime.events import MessageReceived
    from bob.social.interlocutor import InterlocutorKind
    from bob.social.usecases.authorizer import Authorizer


class GenderMemory(Protocol):
    """Seam: accrue + read a sender's self-identified gender (BOB-078 A).

    :meth:`observe_gender` folds this turn's text into the sender's accrued
    self-presentation; :meth:`load_gender` reads the resolved :class:`Gender`
    (UNKNOWN until a self-signal clears the threshold). Realised by
    :class:`~bob.social.adapters.relationship_store.SqliteRelationshipStore`.
    Optional and additive — unwired, every sender reads UNKNOWN and the turn is
    unchanged.
    """

    async def observe_gender(self, sender_id: int, text: str) -> None: ...

    async def load_gender(self, sender_id: int) -> Gender: ...


class SenderPerception:
    """Resolve a received message into an :class:`Interlocutor` via the Authorizer."""

    def __init__(
        self, *, authorizer: Authorizer, gender_store: GenderMemory | None = None
    ) -> None:
        self._authorizer = authorizer
        self._gender_store = gender_store

    async def resolve(self, event: MessageReceived) -> Interlocutor:
        """Perceive WHO sent ``event`` — owner / known / guest (+ trust + gender).

        Owner recognition is identity-only (not chat-scoped), so Bob knows his
        owner even outside an allowed chat; ``is_authorized`` runs the full
        chat-scoped policy for everyone else. When a gender seam is wired (BOB-078 A),
        this turn's text is first folded into the sender's self-presentation and their
        resolved :class:`Gender` is read back so Bob addresses them in the right
        grammatical gender (UNKNOWN → neutral, never guessed from a name). Pure
        perception — no access decision is made or changed here.
        """
        is_owner = self._authorizer.is_owner(event.sender_id)
        is_authorized = await self._authorizer.is_authorized(
            user_id=event.sender_id, chat_id=event.chat_id
        )
        gender = await self._perceive_gender(event)
        return classify(
            sender_id=event.sender_id,
            sender_name=event.sender_name,
            is_owner=is_owner,
            is_authorized=is_authorized,
            gender=gender,
            # BOB-090.B3: their @handle rides along with the identity so the roster can
            # store it and Bob can address them for real instead of composing «@Норман».
            username=event.sender_username,
        )

    async def perceive_kind(self, event: MessageReceived) -> InterlocutorKind:
        """Perceive only the sender's social :class:`InterlocutorKind` (BOB-078 B).

        A lighter sibling of :meth:`resolve` for the holistic stream-read: it runs the SAME
        authz classification (owner / known / guest) but deliberately does NOT accrue gender —
        self-presentation is already folded on the main handle path, so re-observing it here
        would double-count. Pure perception, no access decision changed.
        """
        is_owner = self._authorizer.is_owner(event.sender_id)
        is_authorized = await self._authorizer.is_authorized(
            user_id=event.sender_id, chat_id=event.chat_id
        )
        return classify(
            sender_id=event.sender_id,
            sender_name=event.sender_name,
            is_owner=is_owner,
            is_authorized=is_authorized,
        ).kind

    async def _perceive_gender(self, event: MessageReceived) -> Gender:
        """Accrue this turn's self-presentation and read back the sender's gender.

        A no-op (UNKNOWN) with no gender seam wired or no keyable ``sender_id`` —
        gender is per-PERSON, so it needs an id to accrue against.
        """
        if self._gender_store is None or event.sender_id is None:
            return Gender.UNKNOWN
        await self._gender_store.observe_gender(event.sender_id, event.text)
        return await self._gender_store.load_gender(event.sender_id)
