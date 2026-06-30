# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""KvNotableReactionStore — the light being-received note adapter (BOB-050).

Realises :class:`bob.domain.ports.NotableReactionStore` over the generic ``kv`` table
(no new schema/migration): a single JSON row under one key holding the MOST RECENT
:class:`~bob.domain.personality.reaction_effect.NotableReaction`. Deliberately tiny —
the rare-aloud hint (BOB-050 .3) only ever needs the latest moment Bob was received,
not a log — so :meth:`record` overwrites and :meth:`latest` reads that one row. A
missing or unparseable row yields ``None`` (a clean no-op), so a malformed note can
never break the decorative perceiving path. All access goes through the repo's
parameterised ``kv_set`` / ``kv_get`` — never an f-string SQL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Protocol

from bob.domain.personality.reaction_effect import NotableReaction

logger = logging.getLogger(__name__)

# The single kv key holding the most-recent being-received reaction.
_KEY = "notable_reaction.latest"

# Tombstone written by :meth:`KvNotableReactionStore.clear` — an empty value reads back
# as "nothing on record" WITHOUT tripping the unreadable-note warning (a clean consume).
_CLEARED = ""


class _KvStore(Protocol):
    """The key/value seam the store needs (realised by SqliteMemoryRepo)."""

    async def kv_set(self, key: str, value: str) -> None: ...

    async def kv_get(self, key: str) -> str | None: ...


class KvNotableReactionStore:
    """SQLite ``kv``-backed adapter for the latest being-received reaction (BOB-050)."""

    def __init__(self, repo: _KvStore) -> None:
        self._repo = repo

    async def record(self, note: NotableReaction) -> None:
        """Persist ``note`` as the most recent being-received reaction (overwrites)."""
        await self._repo.kv_set(_KEY, _encode(note))

    async def latest(self) -> NotableReaction | None:
        """Return the most recent recorded reaction, or ``None`` if absent/unreadable."""
        raw = await self._repo.kv_get(_KEY)
        if not raw:
            return None
        return _decode(raw)

    async def clear(self) -> None:
        """Consume the recorded reaction (BOB-050 .3) so it is acknowledged at most once.

        Writes an empty tombstone so a later :meth:`latest` cleanly reads ``None`` —
        the rare-aloud hint surfaces a moment, then clears it so Bob never repeats the
        same acknowledgment on a following turn.
        """
        await self._repo.kv_set(_KEY, _CLEARED)


def _encode(note: NotableReaction) -> str:
    """Serialise a :class:`NotableReaction` to a JSON string."""
    return json.dumps(
        {
            "sender_id": note.sender_id,
            "reactor_name": note.reactor_name,
            "emoji": note.emoji,
            "bob_excerpt": note.bob_excerpt,
            "interpretation": note.interpretation,
            "at": note.at.isoformat(),
        }
    )


def _decode(raw: str) -> NotableReaction | None:
    """Parse a JSON string back into a :class:`NotableReaction` (None on garbage)."""
    try:
        data = json.loads(raw)
        sender = data["sender_id"]
        return NotableReaction(
            sender_id=None if sender is None else int(sender),
            reactor_name=str(data["reactor_name"]),
            emoji=str(data["emoji"]),
            bob_excerpt=str(data["bob_excerpt"]),
            interpretation=str(data["interpretation"]),
            at=datetime.fromisoformat(str(data["at"])),
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("ignoring an unreadable notable-reaction note")
        return None
