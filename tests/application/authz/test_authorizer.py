# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the Authorizer — pure access policy (owner + allowlist + chat-scope).

The policy is exercised over a fake in-memory allowlist store so persistence is
out of scope here: only the decision rules (owner always allowed; otherwise the
user must be allowlisted AND the chat must be in the allowed chat set) are tested.
"""

from __future__ import annotations

from bob.social.usecases import Authorizer

_OWNER = 1
_CHAT = 100


class _FakeAllowlistStore:
    """In-memory AllowlistStore double recording loads/adds for assertions."""

    def __init__(self, initial: set[int] | None = None) -> None:
        self.users: set[int] = set(initial) if initial else set()
        self.added: list[int] = []
        self.removed: list[int] = []

    async def load(self) -> set[int]:
        return set(self.users)

    async def add(self, user_id: int) -> None:
        self.users.add(user_id)
        self.added.append(user_id)

    async def remove(self, user_id: int) -> None:
        self.users.discard(user_id)
        self.removed.append(user_id)


def _authorizer(
    *,
    store: _FakeAllowlistStore | None = None,
    allowed_chats: frozenset[int] = frozenset({_CHAT}),
) -> tuple[Authorizer, _FakeAllowlistStore]:
    used = store if store is not None else _FakeAllowlistStore()
    return (
        Authorizer(owner_id=_OWNER, allowed_chat_ids=allowed_chats, store=used),
        used,
    )


async def test_owner_is_authorized_in_allowed_chat() -> None:
    authorizer, _ = _authorizer()

    assert await authorizer.is_authorized(user_id=_OWNER, chat_id=_CHAT) is True


async def test_owner_is_rejected_in_a_disallowed_chat() -> None:
    # Chat-scope binds even the owner: a leaked token in a foreign chat is dead.
    authorizer, _ = _authorizer()

    assert await authorizer.is_authorized(user_id=_OWNER, chat_id=999) is False


async def test_unknown_user_in_allowed_chat_is_rejected() -> None:
    authorizer, _ = _authorizer()

    assert await authorizer.is_authorized(user_id=42, chat_id=_CHAT) is False


async def test_allowlisted_user_in_allowed_chat_is_authorized() -> None:
    store = _FakeAllowlistStore(initial={42})
    authorizer, _ = _authorizer(store=store)

    assert await authorizer.is_authorized(user_id=42, chat_id=_CHAT) is True


async def test_allowlisted_user_in_disallowed_chat_is_rejected() -> None:
    store = _FakeAllowlistStore(initial={42})
    authorizer, _ = _authorizer(store=store)

    assert await authorizer.is_authorized(user_id=42, chat_id=999) is False


async def test_none_user_is_rejected() -> None:
    authorizer, _ = _authorizer()

    assert await authorizer.is_authorized(user_id=None, chat_id=_CHAT) is False


async def test_authorize_adds_user_and_persists() -> None:
    authorizer, store = _authorizer()

    await authorizer.authorize(42)

    assert store.added == [42]
    assert await authorizer.is_authorized(user_id=42, chat_id=_CHAT) is True


async def test_deauthorize_removes_user_and_persists() -> None:
    store = _FakeAllowlistStore(initial={42})
    authorizer, used = _authorizer(store=store)

    await authorizer.deauthorize(42)

    assert used.removed == [42]
    assert await authorizer.is_authorized(user_id=42, chat_id=_CHAT) is False


async def test_is_owner_distinguishes_the_owner() -> None:
    authorizer, _ = _authorizer()

    assert authorizer.is_owner(_OWNER) is True
    assert authorizer.is_owner(42) is False
