# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ConsolidateMemory — the rare, non-destructive digest step (BOB-021).

On the reflect tick Bob folds OLD un-consolidated episodes into a Tier-0 digest
(a normal ``episodic_log`` row, embedded on write) and flags the sources — never
deleting them. Covered here on fakes (no network): eligible old episodes produce a
digest and flag their sources; idempotency (a second run with nothing eligible is a
no-op, no duplicate digest); digests are excluded from re-consolidation;
non-destructive (originals remain); thresholds come from config; an empty Tier-0
summary is a safe no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.consolidate_memory import ConsolidateMemory

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.application.router.llm_router import LLMRequest

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeRouter:
    """Records requests and replies with a scripted digest line."""

    def __init__(self, reply: str = "Сжатый дайджест: имена и решения сохранены.") -> None:
        self.reply = reply
        self.requests: list[LLMRequest] = []

    async def run(self, request: LLMRequest) -> str:
        self.requests.append(request)
        return self.reply


class FakeConsolidationStore:
    """In-memory double for the consolidation persistence seam.

    Holds episodes as (id, ts, event_type, content) and tracks digests written +
    ids flagged consolidated. ``select_consolidatable_episodes`` mirrors the SQL
    predicate: old, un-consolidated, non-digest, oldest first, capped by ``limit``.
    """

    def __init__(self, episodes: list[dict[str, object]]) -> None:
        self.episodes = episodes
        self.digests: list[Mapping[str, object]] = []
        self.flagged: list[int] = []

    async def select_consolidatable_episodes(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[Mapping[str, object]]:
        eligible = [
            e
            for e in self.episodes
            if e["event_type"] != "digest"
            and int(str(e["id"])) not in self.flagged
            and datetime.fromisoformat(str(e["ts"])) < older_than
        ]
        eligible.sort(key=lambda e: str(e["ts"]))
        return eligible[:limit]

    async def save_digest(self, digest: Mapping[str, object]) -> None:
        self.digests.append(digest)
        self.episodes.append(
            {
                "id": 1000 + len(self.digests),
                "ts": digest["ts"],
                "event_type": "digest",
                "content": digest["content"],
            }
        )

    async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
        self.flagged.extend(episode_ids)


def _ep(eid: int, *, day: int, content: str, event_type: str = "message") -> dict[str, object]:
    return {
        "id": eid,
        "ts": datetime(2026, 6, day, 9, 0, tzinfo=UTC).isoformat(),
        "event_type": event_type,
        "content": content,
    }


def _consolidate(
    store: FakeConsolidationStore,
    router: FakeRouter,
    *,
    max_age_days: float = 14.0,
    batch_size: int = 50,
) -> ConsolidateMemory:
    return ConsolidateMemory(
        store=store,
        router=router,
        clock=FakeClock(_NOW),
        max_age_days=max_age_days,
        batch_size=batch_size,
    )


async def test_old_episodes_become_a_digest_and_sources_are_flagged() -> None:
    # Arrange: two OLD message episodes (older than 14 days before NOW).
    store = FakeConsolidationStore(
        [_ep(1, day=1, content="старое A"), _ep(2, day=2, content="старое B")]
    )
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: exactly one digest written, and both sources flagged consolidated.
    assert len(store.digests) == 1
    assert store.digests[0]["content"] == router.reply
    assert sorted(store.flagged) == [1, 2]


async def test_digest_summarisation_runs_on_tier0() -> None:
    # Arrange
    store = FakeConsolidationStore([_ep(1, day=1, content="старое A")])
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: the summary prompt went through the router (Tier-0 task) with the
    # source content as grounding context — local, no network.
    assert len(router.requests) == 1
    request = router.requests[0]
    grounding = (request.shareable_context or "") + (request.private_context or "")
    assert "старое A" in grounding


async def test_recent_episodes_are_left_alone() -> None:
    # Arrange: a RECENT episode (1 day old) plus an old one.
    store = FakeConsolidationStore(
        [_ep(1, day=1, content="старое"), _ep(2, day=29, content="свежее")]
    )
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: only the old one is folded; the recent stays un-flagged.
    assert store.flagged == [1]


async def test_second_run_with_nothing_eligible_is_a_noop() -> None:
    # Arrange: one old episode, consolidated on the first run.
    store = FakeConsolidationStore([_ep(1, day=1, content="старое")])
    router = FakeRouter()
    usecase = _consolidate(store, router)
    await usecase.run()

    # Act: a second run — nothing eligible now.
    await usecase.run()

    # Assert: idempotent — still exactly one digest, no extra flagging.
    assert len(store.digests) == 1
    assert store.flagged == [1]


async def test_digests_are_never_re_consolidated() -> None:
    # Arrange: an OLD digest already on record (plus nothing else eligible).
    store = FakeConsolidationStore(
        [_ep(99, day=1, content="старый дайджест", event_type="digest")]
    )
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: a digest is never itself digested — clean no-op.
    assert store.digests == []
    assert store.flagged == []


async def test_consolidation_is_non_destructive() -> None:
    # Arrange
    store = FakeConsolidationStore(
        [_ep(1, day=1, content="старое A"), _ep(2, day=2, content="старое B")]
    )
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: originals are still present (only flagged, never removed).
    contents = {str(e["content"]) for e in store.episodes if e["event_type"] != "digest"}
    assert contents == {"старое A", "старое B"}


async def test_batch_size_caps_one_run() -> None:
    # Arrange: three old episodes, batch size 2.
    store = FakeConsolidationStore(
        [_ep(1, day=1, content="A"), _ep(2, day=2, content="B"), _ep(3, day=3, content="C")]
    )
    router = FakeRouter()

    # Act
    await _consolidate(store, router, batch_size=2).run()

    # Assert: only the first two oldest are folded this run.
    assert sorted(store.flagged) == [1, 2]


async def test_age_threshold_comes_from_config() -> None:
    # Arrange: an episode 10 days old; a 14-day threshold spares it, a 7-day folds it.
    store = FakeConsolidationStore([_ep(1, day=20, content="десятидневное")])
    router = FakeRouter()

    # Act / Assert: with a 14-day threshold it is too recent — no-op.
    await _consolidate(store, router, max_age_days=14.0).run()
    assert store.digests == []

    # With a 7-day threshold it is now old enough — folded.
    await _consolidate(store, router, max_age_days=7.0).run()
    assert len(store.digests) == 1


async def test_empty_summary_is_a_safe_noop() -> None:
    # Arrange: Tier 0 returns nothing usable.
    store = FakeConsolidationStore([_ep(1, day=1, content="старое")])
    router = FakeRouter(reply="   ")

    # Act
    await _consolidate(store, router).run()

    # Assert: no digest written and sources NOT flagged (so a later run can retry).
    assert store.digests == []
    assert store.flagged == []


async def test_empty_archive_is_a_noop() -> None:
    # Arrange
    store = FakeConsolidationStore([])
    router = FakeRouter()

    # Act
    await _consolidate(store, router).run()

    # Assert: nothing to do, no router call, no digest.
    assert router.requests == []
    assert store.digests == []
