# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Authorizer — the pure access policy guarding every inbound interaction.

Bob is private: only the **owner** and **allowlisted** users, and only inside the
**allowed chats**, may interact. Everyone else is silently ignored at the single
gateway gate. This module is the decision rule, with no transport or SQL:

* ``is_authorized(user_id, chat_id)`` — owner is allowed only inside an allowed
  chat (chat-scope binds even the owner, so a leaked token in a foreign chat is
  dead); any other user must be on the allowlist AND inside an allowed chat.
* ``authorize`` / ``deauthorize`` — mutate the runtime allowlist and persist it
  through the injected :class:`bob.domain.ports.AllowlistStore` so ``/authorize``
  survives a restart.

The configured ``owner_id`` / ``allowed_chat_ids`` are immutable for the process;
the dynamic allowlist is read fresh from the store on each decision so a grant on
one process is honoured everywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bob.domain.ports import AllowlistStore


class Authorizer:
    """Owner + allowlist + chat-scope access policy over an AllowlistStore."""

    def __init__(
        self,
        *,
        owner_id: int,
        allowed_chat_ids: Iterable[int],
        store: AllowlistStore,
    ) -> None:
        self._owner_id = owner_id
        self._allowed_chat_ids = frozenset(allowed_chat_ids)
        self._store = store

    def is_owner(self, user_id: int | None) -> bool:
        """Whether ``user_id`` is the configured owner."""
        return user_id is not None and user_id == self._owner_id

    async def is_authorized(self, *, user_id: int | None, chat_id: int) -> bool:
        """Decide whether ``user_id`` may interact from ``chat_id``.

        Chat-scope is checked first: a message from a chat outside
        ``allowed_chat_ids`` is rejected for everyone, owner included. Inside an
        allowed chat, the owner is always allowed; any other user must be on the
        persisted allowlist.
        """
        if user_id is None or chat_id not in self._allowed_chat_ids:
            return False
        if user_id == self._owner_id:
            return True
        return user_id in await self._store.load()

    async def authorize(self, user_id: int) -> None:
        """Add ``user_id`` to the allowlist and persist the grant."""
        await self._store.add(user_id)

    async def deauthorize(self, user_id: int) -> None:
        """Remove ``user_id`` from the allowlist and persist the revocation."""
        await self._store.remove(user_id)
