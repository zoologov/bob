# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""ReactorPerception — turn a reactor's id+name into an Interlocutor (BOB-050).

The reaction-side sibling of :class:`~bob.social.usecases.sender_perception.SenderPerception`:
it composes the unchanged access policy
(:class:`~bob.social.usecases.authorizer.Authorizer`) with the pure domain
:func:`~bob.social.interlocutor.classify` so the person who reacted to one
of Bob's messages becomes an
:class:`~bob.social.interlocutor.Interlocutor` (owner / known / guest +
trust). The perceiving use-case folds that identity into the reaction judgment.

This is perception, NOT a gate: it reads ``is_owner`` (identity, not chat-scoped) and
``is_authorized`` (the full chat-scoped policy) but changes no access decision — a
guest may react and be felt; authz containment (no owner-private leak) is preserved
because the perceiving path only ever touches per-person data about Bob's OWN message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.social.interlocutor import Interlocutor, classify

if TYPE_CHECKING:
    from bob.social.usecases.authorizer import Authorizer


class ReactorPerception:
    """Resolve a reactor's id+name into an :class:`Interlocutor` via the Authorizer."""

    def __init__(self, *, authorizer: Authorizer) -> None:
        self._authorizer = authorizer

    async def resolve(
        self, *, sender_id: int | None, sender_name: str | None, chat_id: int
    ) -> Interlocutor:
        """Perceive WHO reacted — owner / known / guest (+ trust).

        Owner recognition is identity-only (not chat-scoped), so Bob knows his owner
        wherever the reaction came from; ``is_authorized`` runs the full chat-scoped
        policy for everyone else. Pure perception — no access decision is made here.
        """
        is_owner = self._authorizer.is_owner(sender_id)
        is_authorized = await self._authorizer.is_authorized(
            user_id=sender_id, chat_id=chat_id
        )
        return classify(
            sender_id=sender_id,
            sender_name=sender_name,
            is_owner=is_owner,
            is_authorized=is_authorized,
        )
