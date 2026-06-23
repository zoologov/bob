# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SenderPerception — Authorizer → Interlocutor adapter (BOB-019).

The perception adapter composes the unchanged access policy (:class:`Authorizer`)
with the pure :func:`classify` so a received message becomes an
:class:`Interlocutor` (owner / known / guest + trust). It is the wiring seam
:class:`HandleMessage` uses to perceive WHO is writing; the authz decision itself
is untouched (perception, not a gate). Exercised over a fake allowlist store — no
SQL, no transport.
"""

from __future__ import annotations

from bob.application.authz import Authorizer, SenderPerception
from bob.application.runtime.events import MessageReceived
from bob.domain.personality.interlocutor import InterlocutorKind, Trust

_OWNER = 1
_CHAT = 100


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


def _perception(*, allowlist: set[int] | None = None) -> SenderPerception:
    authorizer = Authorizer(
        owner_id=_OWNER,
        allowed_chat_ids=[_CHAT],
        store=_FakeAllowlistStore(allowlist),
    )
    return SenderPerception(authorizer=authorizer)


def _event(*, sender_id: int | None, name: str | None = "Someone") -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=_CHAT,
        message_id=1,
        text="hi",
        sender_id=sender_id,
        sender_name=name,
    )


async def test_owner_message_resolves_to_owner_trusted() -> None:
    who = await _perception().resolve(_event(sender_id=_OWNER, name="Vova"))
    assert who.kind is InterlocutorKind.OWNER
    assert who.trust is Trust.TRUSTED
    assert who.display_name == "Vova"


async def test_allowlisted_user_resolves_to_known_trusted() -> None:
    perception = _perception(allowlist={7})
    who = await perception.resolve(_event(sender_id=7, name="Ada"))
    assert who.kind is InterlocutorKind.KNOWN
    assert who.trust is Trust.TRUSTED


async def test_unknown_user_resolves_to_guest() -> None:
    who = await _perception().resolve(_event(sender_id=999, name="Rando"))
    assert who.kind is InterlocutorKind.GUEST
    assert who.trust is Trust.GUEST


async def test_owner_outside_allowed_chat_is_still_recognised_as_owner() -> None:
    # is_owner is identity (not chat-scoped), so even outside the allowed chat Bob
    # still recognises his owner AS owner — perception, not the access gate.
    perception = _perception()
    event = MessageReceived(
        update_id=1,
        chat_id=999,  # not an allowed chat
        message_id=1,
        text="hi",
        sender_id=_OWNER,
        sender_name="Vova",
    )
    who = await perception.resolve(event)
    assert who.kind is InterlocutorKind.OWNER


async def test_missing_sender_id_resolves_to_guest() -> None:
    who = await _perception().resolve(_event(sender_id=None, name=None))
    assert who.kind is InterlocutorKind.GUEST
