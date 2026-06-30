# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ReactorPerception — Authorizer → Interlocutor for a reactor (BOB-050).

The reaction-side sibling of :class:`SenderPerception`: the person who placed/removed
a reaction on one of Bob's messages becomes an :class:`Interlocutor` (owner / known /
guest + trust) via the unchanged access policy. 🔴 US-6 authz: this is PERCEPTION, not
a gate — a guest reacting is FELT (resolved to a guest Interlocutor), owner recognition
is identity-only (works in any chat), and no access decision is made here. The
perceiving use-case folds this identity into the reaction judgment, keyed per-person.
"""

from __future__ import annotations

from bob.application.authz import Authorizer, ReactorPerception
from bob.domain.personality.interlocutor import InterlocutorKind, Trust

_OWNER = 1
_CHAT = 100
_OTHER_CHAT = 999


class _FakeAllowlistStore:
    """In-memory AllowlistStore double."""

    def __init__(self, initial: set[int] | None = None) -> None:
        self.users: set[int] = set(initial) if initial else set()

    async def load(self) -> set[int]:
        return set(self.users)

    async def add(self, user_id: int) -> None:
        self.users.add(user_id)

    async def remove(self, user_id: int) -> None:
        self.users.discard(user_id)


def _perception(*, allowlist: set[int] | None = None) -> ReactorPerception:
    authorizer = Authorizer(
        owner_id=_OWNER,
        allowed_chat_ids=[_CHAT],
        store=_FakeAllowlistStore(allowlist),
    )
    return ReactorPerception(authorizer=authorizer)


async def test_owner_reactor_resolves_to_owner_trusted() -> None:
    who = await _perception().resolve(
        sender_id=_OWNER, sender_name="Vova", chat_id=_CHAT
    )
    assert who.kind is InterlocutorKind.OWNER
    assert who.trust is Trust.TRUSTED
    assert who.display_name == "Vova"


async def test_allowlisted_reactor_resolves_to_known_trusted() -> None:
    who = await _perception(allowlist={7}).resolve(
        sender_id=7, sender_name="Ada", chat_id=_CHAT
    )
    assert who.kind is InterlocutorKind.KNOWN
    assert who.trust is Trust.TRUSTED


async def test_unknown_reactor_is_felt_as_guest_not_gated() -> None:
    # 🔴 US-6: a guest may react and is FELT — perception resolves them to a guest
    # Interlocutor (no exception, no access denial here; this is not the gate).
    who = await _perception().resolve(
        sender_id=999, sender_name="Rando", chat_id=_CHAT
    )
    assert who.kind is InterlocutorKind.GUEST
    assert who.trust is Trust.GUEST


async def test_owner_reacting_outside_allowed_chat_is_still_owner() -> None:
    # is_owner is identity (not chat-scoped): Bob recognises his owner's reaction
    # wherever it lands — perception, not the access gate.
    who = await _perception().resolve(
        sender_id=_OWNER, sender_name="Vova", chat_id=_OTHER_CHAT
    )
    assert who.kind is InterlocutorKind.OWNER


async def test_anonymous_reactor_resolves_to_guest() -> None:
    # No reactor id (anonymous reaction) -> a guest, never mistaken for the owner.
    who = await _perception().resolve(
        sender_id=None, sender_name=None, chat_id=_CHAT
    )
    assert who.kind is InterlocutorKind.GUEST
    assert who.trust is Trust.GUEST


async def test_allowlisted_reactor_in_other_chat_is_guest_there() -> None:
    # A known user reacting in a NON-allowed chat is not authorised THERE -> guest;
    # the chat-scoped policy still applies to perception of non-owners.
    who = await _perception(allowlist={7}).resolve(
        sender_id=7, sender_name="Ada", chat_id=_OTHER_CHAT
    )
    assert who.kind is InterlocutorKind.GUEST
