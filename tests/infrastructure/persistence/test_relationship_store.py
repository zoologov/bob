# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteRelationshipStore — the per-sender relationship adapter (BOB-014).

Round-trips the domain :class:`Relationship` (sender_id + the four bounded axes)
into a per-``sender_id`` SQLite row: the ``None`` default for an unknown sender, the
save→load round-trip, that a later save UPDATES the row (a relationship evolves over
turns — unlike the formed-once first impression), per-sender isolation (owner vs
guest stay distinct), and survival across a restart. Keyed by sender_id so it works
for owner / known / guest / bot alike — per-PERSON data, not owner-private memory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.kernel.interlocutor import Gender
from bob.kernel.relationship import Relationship
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.social.adapters.relationship_store import SqliteRelationshipStore

if TYPE_CHECKING:
    from pathlib import Path

_SENDER = 4242
_OTHER_SENDER = 9999


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_load_returns_none_for_unknown_sender(repo: SqliteMemoryRepo) -> None:
    store = SqliteRelationshipStore(repo)

    assert await store.load(_SENDER) is None


async def test_save_then_load_round_trips(repo: SqliteMemoryRepo) -> None:
    store = SqliteRelationshipStore(repo)
    rel = Relationship(
        sender_id=_SENDER, trust=0.3, respect=0.1, warmth=0.5, compatibility=-0.2
    )

    await store.save(rel)
    loaded = await store.load(_SENDER)

    assert loaded == rel


async def test_save_updates_an_evolving_relationship(repo: SqliteMemoryRepo) -> None:
    store = SqliteRelationshipStore(repo)
    await store.save(Relationship(sender_id=_SENDER, warmth=0.1))

    # Unlike the formed-once first impression, a relationship is re-saved as it
    # evolves — a later save overwrites the row with the newer state.
    updated = Relationship(sender_id=_SENDER, warmth=0.6, trust=0.2)
    await store.save(updated)

    assert await store.load(_SENDER) == updated


async def test_is_per_sender_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteRelationshipStore(repo)
    owner = Relationship(sender_id=_SENDER, warmth=0.8)

    await store.save(owner)

    assert await store.load(_SENDER) == owner
    assert await store.load(_OTHER_SENDER) is None


async def test_gender_defaults_unknown_for_unknown_sender(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteRelationshipStore(repo)

    assert await store.load_gender(_SENDER) is Gender.UNKNOWN


async def test_observe_gender_reads_feminine_self_presentation(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteRelationshipStore(repo)

    # BOB-078.8: коммит рода требует ≥2 согласных само-сигналов (один лишь наклоняет).
    await store.observe_gender(_SENDER, "Пошла учить Python")
    await store.observe_gender(_SENDER, "Я разобралась потом")

    assert await store.load_gender(_SENDER) is Gender.FEM


async def test_single_self_signal_does_not_commit_gender(
    repo: SqliteMemoryRepo,
) -> None:
    # 🔴 BOB-078.8: ОДИН родовой сигнал только наклоняет lean — наружу ещё UNKNOWN
    # (ведущий глагол вроде «Была ошибка…» не переворачивает пол за один ход).
    store = SqliteRelationshipStore(repo)

    await store.observe_gender(_SENDER, "Была ошибка в коде")

    assert await store.load_gender(_SENDER) is Gender.UNKNOWN


async def test_observe_gender_never_infers_from_a_name(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteRelationshipStore(repo)

    await store.observe_gender(_SENDER, "Меня зовут Лиля")

    assert await store.load_gender(_SENDER) is Gender.UNKNOWN


async def test_observe_gender_accumulates_across_turns(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteRelationshipStore(repo)

    await store.observe_gender(_SENDER, "Пролистала чат")
    await store.observe_gender(_SENDER, "и я сделала всё сама")

    assert await store.load_gender(_SENDER) is Gender.FEM


async def test_observe_gender_leaves_relationship_axes_untouched(
    repo: SqliteMemoryRepo,
) -> None:
    store = SqliteRelationshipStore(repo)
    rel = Relationship(sender_id=_SENDER, warmth=0.7, trust=0.3)
    await store.save(rel)

    await store.observe_gender(_SENDER, "я сделал")
    await store.observe_gender(_SENDER, "я разобрался сам")

    assert await store.load(_SENDER) == rel
    assert await store.load_gender(_SENDER) is Gender.MASC


async def test_gender_is_per_sender_isolated(repo: SqliteMemoryRepo) -> None:
    store = SqliteRelationshipStore(repo)

    await store.observe_gender(_SENDER, "Пошла спать")
    await store.observe_gender(_SENDER, "я убрала всё")

    assert await store.load_gender(_SENDER) is Gender.FEM
    assert await store.load_gender(_OTHER_SENDER) is Gender.UNKNOWN


async def test_gender_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"

    first = SqliteMemoryRepo(db)
    await first.initialize()
    first_store = SqliteRelationshipStore(first)
    await first_store.observe_gender(_SENDER, "Пошла учить Python")
    await first_store.observe_gender(_SENDER, "Я разобралась потом")
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteRelationshipStore(second).load_gender(_SENDER)
    await second.close()

    assert loaded is Gender.FEM


async def test_survives_restart(tmp_path: Path) -> None:
    db = tmp_path / "bob.db"
    rel = Relationship(sender_id=_SENDER, trust=0.4, warmth=0.4)

    first = SqliteMemoryRepo(db)
    await first.initialize()
    await SqliteRelationshipStore(first).save(rel)
    await first.close()

    second = SqliteMemoryRepo(db)
    await second.initialize()
    loaded = await SqliteRelationshipStore(second).load(_SENDER)
    await second.close()

    assert loaded == rel
