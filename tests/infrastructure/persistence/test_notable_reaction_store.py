# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for KvNotableReactionStore — the light being-received note adapter (BOB-050 .2).

A single most-recent record round-tripped through the generic ``kv`` table: record
overwrites, latest reads it back, an absent or unreadable row yields ``None`` (a clean
no-op so a malformed note never breaks the decorative perceiving path).
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.domain.personality.reaction_effect import NotableReaction
from bob.infrastructure.persistence.notable_reaction_store import KvNotableReactionStore


class _FakeKv:
    """In-memory kv stand-in for SqliteMemoryRepo's kv_set/kv_get."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def kv_set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def kv_get(self, key: str) -> str | None:
        return self.data.get(key)


def _note() -> NotableReaction:
    return NotableReaction(
        sender_id=42,
        reactor_name="Боб-старший",
        emoji="❤",
        bob_excerpt="я правда рад",
        interpretation="его тронуло",
        at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
    )


async def test_latest_is_none_when_empty() -> None:
    store = KvNotableReactionStore(_FakeKv())
    assert await store.latest() is None


async def test_record_then_latest_round_trips() -> None:
    store = KvNotableReactionStore(_FakeKv())
    note = _note()

    await store.record(note)
    loaded = await store.latest()

    assert loaded == note


async def test_record_overwrites_the_single_row() -> None:
    kv = _FakeKv()
    store = KvNotableReactionStore(kv)

    await store.record(_note())
    newer = NotableReaction(
        sender_id=7,
        reactor_name="гость",
        emoji="🔥",
        bob_excerpt="привет",
        interpretation="оценил",
        at=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
    )
    await store.record(newer)

    assert await store.latest() == newer


async def test_unreadable_row_yields_none() -> None:
    kv = _FakeKv()
    kv.data["notable_reaction.latest"] = "{ not json"
    store = KvNotableReactionStore(kv)
    assert await store.latest() is None
