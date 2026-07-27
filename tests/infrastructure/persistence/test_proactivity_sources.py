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
from bob.proactivity.adapters.proactivity_sources import RepoProactivitySources

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
async def test_latest_salience_uses_system_clock_when_none_injected(tmp_path: Path) -> None:
    # Arrange: no clock injected — the adapter falls back to its internal UTC
    # system clock (the production-wiring default). A reflection stamped at the
    # real "now" must still read as fresh (salience near full).
    repo = await _repo(tmp_path)
    now = datetime.now(tz=UTC)
    await _add_episode(
        repo,
        event_type="reflection",
        content="A thought I am having right now.",
        ts=now,
        tags="heartbeat",
    )
    sources = RepoProactivitySources(repo)  # no clock= → _SystemClock fallback
    try:
        salience = await sources.latest_salience()
    finally:
        await repo.close()

    # Assert: a just-written reflection scores high even through the wall-clock
    # fallback; a tiny processing delay keeps it well inside the 6h horizon.
    assert salience > 0.99


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


@pytest.mark.asyncio
async def test_latest_reflection_text_returns_most_recent_real_reflection(
    tmp_path: Path,
) -> None:
    # BOB-018 leak seam: the newest reflection/inner_monologue text comes back so the
    # reactive reply can leak it (here the inner_monologue is the most recent).
    repo = await _repo(tmp_path)
    await _add_episode(
        repo,
        event_type="reflection",
        content="старая рефлексия",
        ts=_NOW - timedelta(hours=2),
    )
    await _add_episode(
        repo,
        event_type="inner_monologue",
        content="свежая внутренняя мысль про космос",
        ts=_NOW,
    )
    sources = RepoProactivitySources(repo)
    try:
        text = await sources.latest_reflection_text()
    finally:
        await repo.close()
    assert text == "свежая внутренняя мысль про космос"


@pytest.mark.asyncio
async def test_latest_reflection_text_is_none_without_any_inner_life(
    tmp_path: Path,
) -> None:
    # Anti-confabulation: a plain conversation turn is NOT inner life, so there is
    # nothing real to leak — the reader returns None and the caller no-ops.
    repo = await _repo(tmp_path)
    await _add_episode(repo, event_type="message", content="привет", ts=_NOW)
    sources = RepoProactivitySources(repo)
    try:
        assert await sources.latest_reflection_text() is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_latest_reflection_text_is_none_on_empty_log(tmp_path: Path) -> None:
    repo = await _repo(tmp_path)
    sources = RepoProactivitySources(repo)
    try:
        assert await sources.latest_reflection_text() is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_latest_reflection_text_is_none_for_whitespace_only_content(
    tmp_path: Path,
) -> None:
    # Anti-confabulation edge: a reflection row whose content is only whitespace has
    # nothing real to leak — the reader normalises it to None so the leak no-ops
    # rather than injecting a blank "thought" into the compose prompt.
    repo = await _repo(tmp_path)
    await _add_episode(repo, event_type="reflection", content="   \n\t  ", ts=_NOW)
    sources = RepoProactivitySources(repo)
    try:
        assert await sources.latest_reflection_text() is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_latest_reflection_text_trims_surrounding_whitespace(
    tmp_path: Path,
) -> None:
    # The leaked text is the trimmed reflection content — no stray newlines/padding
    # bleed into the compose prompt around the real thought.
    repo = await _repo(tmp_path)
    await _add_episode(
        repo, event_type="reflection", content="  думал про звёзды  \n", ts=_NOW
    )
    sources = RepoProactivitySources(repo)
    try:
        text = await sources.latest_reflection_text()
    finally:
        await repo.close()
    assert text == "думал про звёзды"


def _clock(moment: datetime) -> _FixedClock:
    return _FixedClock(moment)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment
