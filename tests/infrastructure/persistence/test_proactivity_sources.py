# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the live proactivity read-seams over the episodic log (BOB-010 Ф1).

The :class:`ProactivityEngine` reads two cheap signals on every tick — how
striking Bob's most recent reflection is (:class:`ReflectionSalienceSource`) and
how many proactive messages he has sent inside the anti-spam window
(:class:`ProactiveWindowCounter`). :class:`RepoProactivitySources` backs both off
the live SQLite ``episodic_log`` (no LLM): a recent ``reflection`` episode yields
a recency-weighted salience, and ``proactive`` episodes inside the window are
counted. These tests pin that mapping against a real temp database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.persistence import SqliteMemoryRepo
from bob.infrastructure.persistence.proactivity_sources import RepoProactivitySources

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 6, 20, 20, 0, tzinfo=UTC)


async def _repo(tmp_path: Path) -> SqliteMemoryRepo:
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    return repo


async def _add_episode(
    repo: SqliteMemoryRepo, *, event_type: str, content: str, ts: datetime, tags: str = ""
) -> None:
    await repo.save_episode(
        {
            "ts": ts.isoformat(),
            "event_type": event_type,
            "content": content,
            "mood_snapshot": None,
            "tags": tags,
        }
    )


@pytest.mark.asyncio
async def test_no_reflection_yields_zero_salience(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    sources = RepoProactivitySources(repo)
    try:
        assert await sources.latest_salience() == 0.0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_recent_reflection_yields_high_salience(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    await _add_episode(
        repo,
        event_type="reflection",
        content="I've been thinking about the probes.",
        ts=_NOW,
        tags="heartbeat",
    )
    sources = RepoProactivitySources(repo, clock=_clock(_NOW))
    try:
        salience = await sources.latest_salience()
    finally:
        await repo.close()
    assert salience > 0.8


@pytest.mark.asyncio
async def test_stale_reflection_decays_salience(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    await _add_episode(
        repo,
        event_type="reflection",
        content="An old thought.",
        ts=_NOW - timedelta(hours=12),
        tags="heartbeat",
    )
    sources = RepoProactivitySources(repo, clock=_clock(_NOW))
    try:
        salience = await sources.latest_salience()
    finally:
        await repo.close()
    assert salience < 0.2


@pytest.mark.asyncio
async def test_message_episode_is_not_a_reflection(tmp_path: Path) -> None:
    # A plain conversation turn is the most-recent episode but must not count as a
    # reflection — only a reflection drives salience.
    repo = await _repo(tmp_path)
    await _add_episode(
        repo, event_type="message", content="hi bob", ts=_NOW, tags="telegram"
    )
    sources = RepoProactivitySources(repo, clock=_clock(_NOW))
    try:
        assert await sources.latest_salience() == 0.0
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_counts_proactive_messages_in_window(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    # Two proactive posts inside the 24h window, one well outside it.
    await _add_episode(
        repo, event_type="proactive", content="hey", ts=_NOW - timedelta(hours=1)
    )
    await _add_episode(
        repo, event_type="proactive", content="you up?", ts=_NOW - timedelta(hours=5)
    )
    await _add_episode(
        repo, event_type="proactive", content="old", ts=_NOW - timedelta(days=3)
    )
    sources = RepoProactivitySources(repo)
    try:
        count = await sources.proactive_count_in_window(now=_NOW)
    finally:
        await repo.close()
    assert count == 2


@pytest.mark.asyncio
async def test_window_count_ignores_non_proactive_episodes(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    await _add_episode(repo, event_type="message", content="hi", ts=_NOW)
    await _add_episode(repo, event_type="reflection", content="hmm", ts=_NOW)
    sources = RepoProactivitySources(repo)
    try:
        assert await sources.proactive_count_in_window(now=_NOW) == 0
    finally:
        await repo.close()


def _clock(moment: datetime) -> _FixedClock:
    return _FixedClock(moment)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment
