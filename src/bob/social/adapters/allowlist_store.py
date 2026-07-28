# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""KvAllowlistStore — durable authorization allowlist over the generic kv table.

Realises :class:`bob.domain.ports.AllowlistStore` by persisting the set of
allowlisted user ids as a JSON array under a single key in the existing ``kv``
table (:meth:`SqliteMemoryRepo.kv_get` / :meth:`~SqliteMemoryRepo.kv_set`). This
keeps all SQL in the repo (parameterised) and lets ``/authorize`` survive a
restart: a fresh process reads the same key and sees the same grants.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# The single kv key under which the allowlist (a JSON list of ints) is stored.
_ALLOWLIST_KEY = "authz.allowlist"


class _KvStore(Protocol):
    """The kv subset the allowlist adapter needs (realised by SqliteMemoryRepo)."""

    async def kv_get(self, key: str) -> str | None: ...
    async def kv_set(self, key: str, value: str) -> None: ...


class KvAllowlistStore:
    """SQLite-backed allowlist persisted as a JSON list under one kv key."""

    def __init__(self, kv: _KvStore) -> None:
        self._kv = kv

    async def load(self) -> set[int]:
        """Return the persisted set of allowlisted user ids (empty if unset)."""
        raw = await self._kv.kv_get(_ALLOWLIST_KEY)
        return _decode(raw)

    async def add(self, user_id: int) -> None:
        """Add ``user_id`` to the allowlist (idempotent) and persist it."""
        users = await self.load()
        if user_id in users:
            return
        users.add(user_id)
        await self._save(users)

    async def remove(self, user_id: int) -> None:
        """Remove ``user_id`` from the allowlist (idempotent) and persist it."""
        users = await self.load()
        if user_id not in users:
            return
        users.discard(user_id)
        await self._save(users)

    async def _save(self, users: Iterable[int]) -> None:
        await self._kv.kv_set(_ALLOWLIST_KEY, json.dumps(sorted(users)))


def _decode(raw: str | None) -> set[int]:
    """Decode the stored JSON array into a set of ints (defensive on shape)."""
    if not raw:
        return set()
    decoded = json.loads(raw)
    if not isinstance(decoded, list):
        logger.warning("allowlist blob is not a JSON list; ignoring")
        return set()
    return {int(item) for item in decoded if isinstance(item, int)}
