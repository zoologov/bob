# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SqliteMemoryRepo — schema init, WAL, and restart persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.memory.entities import EpisodicEvent, SemanticFact

if TYPE_CHECKING:
    from pathlib import Path


def _ts(hour: int = 12) -> datetime:
    return datetime(2026, 6, 18, hour, 0, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path: Path) -> SqliteMemoryRepo:
    instance = SqliteMemoryRepo(tmp_path / "bob.db")
    await instance.initialize()
    return instance


async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "bob.db"
    repo = SqliteMemoryRepo(db_path)

    # Act: running init twice must not raise (CREATE IF NOT EXISTS migrations).
    await repo.initialize()
    await repo.initialize()

    # Assert
    assert db_path.exists()
    await repo.close()


async def test_database_uses_wal_journal_mode(repo: SqliteMemoryRepo) -> None:
    # Act
    mode = await repo.journal_mode()

    # Assert: WAL is required for concurrent reads during a write.
    assert mode.lower() == "wal"
    await repo.close()


async def test_save_and_load_episode_round_trips(repo: SqliteMemoryRepo) -> None:
    # Arrange
    await repo.save_episode(
        {
            "ts": _ts().isoformat(),
            "event_type": "message",
            "content": "hello bob",
            "mood_snapshot": "calm",
            "tags": "greeting,user",
        }
    )

    # Act
    episodes = await repo.load_episodes(limit=10)

    # Assert
    assert len(episodes) == 1
    assert episodes[0]["content"] == "hello bob"
    assert episodes[0]["event_type"] == "message"
    await repo.close()


async def test_load_episodes_returns_newest_first(repo: SqliteMemoryRepo) -> None:
    # Arrange
    for hour, text in ((9, "first"), (10, "second"), (11, "third")):
        await repo.save_episode(
            {"ts": _ts(hour).isoformat(), "event_type": "message", "content": text}
        )

    # Act
    episodes = await repo.load_episodes(limit=2)

    # Assert: most-recent first, honouring the limit.
    assert [e["content"] for e in episodes] == ["third", "second"]
    await repo.close()


async def test_recent_episodes_returns_last_k_in_chronological_order(
    repo: SqliteMemoryRepo,
) -> None:
    # Arrange: four episodes across increasing timestamps.
    for hour, text in ((9, "first"), (10, "second"), (11, "third"), (12, "fourth")):
        await repo.save_episode(
            {"ts": _ts(hour).isoformat(), "event_type": "message", "content": text}
        )

    # Act: ask for the last 2 by recency.
    episodes = await repo.recent_episodes(2)

    # Assert: the two most-recent, returned oldest-first (reads naturally in a prompt).
    assert [e["content"] for e in episodes] == ["third", "fourth"]
    await repo.close()


async def test_recent_episodes_zero_returns_empty(repo: SqliteMemoryRepo) -> None:
    # Arrange
    await repo.save_episode(
        {"ts": _ts().isoformat(), "event_type": "message", "content": "x"}
    )

    # Act / Assert: a non-positive window yields nothing.
    assert await repo.recent_episodes(0) == []
    await repo.close()


async def test_state_survives_a_process_restart(tmp_path: Path) -> None:
    # Arrange: write with one repo instance, then drop it.
    db_path = tmp_path / "bob.db"
    writer = SqliteMemoryRepo(db_path)
    await writer.initialize()
    await writer.save_episode(
        {"ts": _ts().isoformat(), "event_type": "message", "content": "durable"}
    )
    await writer.close()

    # Act: a brand-new instance over the same file simulates a restart.
    reader = SqliteMemoryRepo(db_path)
    await reader.initialize()
    episodes = await reader.load_episodes(limit=10)

    # Assert
    assert [e["content"] for e in episodes] == ["durable"]
    await reader.close()


async def test_save_and_load_semantic_facts(repo: SqliteMemoryRepo) -> None:
    # Arrange
    fact = SemanticFact(ts=_ts(), category="preference", content="bob likes jazz", confidence=0.7)

    # Act
    await repo.save_fact(fact)
    facts = await repo.load_facts(limit=10)

    # Assert
    assert len(facts) == 1
    assert facts[0]["content"] == "bob likes jazz"
    assert facts[0]["category"] == "preference"
    await repo.close()


async def test_save_episode_entity_helper(repo: SqliteMemoryRepo) -> None:
    # Arrange
    event = EpisodicEvent(
        ts=_ts(), event_type="tick", content="heartbeat", tags=("auto",)
    )

    # Act
    await repo.save_episode_entity(event)
    episodes = await repo.load_episodes(limit=10)

    # Assert
    assert episodes[0]["content"] == "heartbeat"
    assert episodes[0]["tags"] == "auto"
    await repo.close()


async def test_mood_state_set_and_get(repo: SqliteMemoryRepo) -> None:
    # Act: setting mood snapshots into history and updates current state.
    await repo.set_mood({"valence": 0.4, "arousal": 0.2}, at=_ts())
    await repo.set_mood({"valence": 0.6, "arousal": 0.1}, at=_ts(13))

    current = await repo.get_mood()
    history = await repo.mood_history(limit=10)

    # Assert
    assert current == {"valence": 0.6, "arousal": 0.1}
    assert len(history) == 2  # both snapshots retained
    await repo.close()


async def test_get_mood_is_none_when_unset(repo: SqliteMemoryRepo) -> None:
    # Act / Assert
    assert await repo.get_mood() is None
    await repo.close()


async def test_taste_axes_upsert_and_read(repo: SqliteMemoryRepo) -> None:
    # Arrange
    await repo.set_taste_axis("humor", value=0.5, conviction=0.3, experience_count=2)
    # Act: upsert the same axis updates in place (no duplicate row).
    await repo.set_taste_axis("humor", value=0.8, conviction=0.6, experience_count=5)
    axes = await repo.load_taste_axes()

    # Assert
    assert len(axes) == 1
    assert axes[0]["axis"] == "humor"
    assert axes[0]["value"] == pytest.approx(0.8)
    assert axes[0]["experience_count"] == 5
    await repo.close()


async def test_relationship_set_and_get(repo: SqliteMemoryRepo) -> None:
    # Act
    await repo.set_relationship({"trust": 0.5, "familiarity": 0.2})
    rel = await repo.get_relationship()

    # Assert
    assert rel == {"trust": 0.5, "familiarity": 0.2}
    await repo.close()


async def test_kv_set_and_get(repo: SqliteMemoryRepo) -> None:
    # Act
    await repo.kv_set("genesis_done", "true")
    value = await repo.kv_get("genesis_done")

    # Assert
    assert value == "true"
    assert await repo.kv_get("absent") is None
    await repo.close()


async def test_kv_survives_restart(tmp_path: Path) -> None:
    # Arrange
    db_path = tmp_path / "bob.db"
    writer = SqliteMemoryRepo(db_path)
    await writer.initialize()
    await writer.kv_set("genesis_done", "true")
    await writer.close()

    # Act
    reader = SqliteMemoryRepo(db_path)
    await reader.initialize()

    # Assert
    assert await reader.kv_get("genesis_done") == "true"
    await reader.close()
