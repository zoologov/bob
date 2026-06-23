# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""SenderPerception — turn an inbound message into an Interlocutor (BOB-019).

The wiring seam that lets Bob *perceive* WHO is writing: it composes the unchanged
access policy (:class:`~bob.application.authz.authorizer.Authorizer`) with the pure
domain :func:`~bob.domain.personality.interlocutor.classify` so a received
:class:`~bob.application.runtime.events.MessageReceived` becomes an
:class:`~bob.domain.personality.interlocutor.Interlocutor` (owner / known / guest /
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

from typing import TYPE_CHECKING

from bob.domain.personality.interlocutor import Interlocutor, classify

if TYPE_CHECKING:
    from bob.application.authz.authorizer import Authorizer
    from bob.application.runtime.events import MessageReceived


class SenderPerception:
    """Resolve a received message into an :class:`Interlocutor` via the Authorizer."""

    def __init__(self, *, authorizer: Authorizer) -> None:
        self._authorizer = authorizer

    async def resolve(self, event: MessageReceived) -> Interlocutor:
        """Perceive WHO sent ``event`` — owner / known / guest (+ trust).

        Owner recognition is identity-only (not chat-scoped), so Bob knows his
        owner even outside an allowed chat; ``is_authorized`` runs the full
        chat-scoped policy for everyone else. Pure perception — no access decision
        is made or changed here.
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
        )
