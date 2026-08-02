# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the work-journal write path — BOB-087.B1.

``DistillingWorkJournalRecorder`` ties the session snapshot → distiller → store: at session
END it writes the distilled first-person episodes as ``work`` events, tagged ``work``/``dev``
+ provenance, visibility owner-private. It is BEST-EFFORT (a distiller/store fault never
breaks the coding session) and skips an empty snapshot. ``NoOpWorkJournalRecorder`` (the
flag-OFF wiring) writes NOTHING — so memory is byte-identical to today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.coding.usecases.distill_work_journal import WorkJournalDistiller  # noqa: TC001
from bob.coding.usecases.work_journal_recorder import (
    DistillingWorkJournalRecorder,
    NoOpWorkJournalRecorder,
)
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
from bob.memory.work_journal import WorkEpisode
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.memory.entities import EpisodicEvent

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_OWNER = 27468732
_FACTS = SessionKeyFacts(files=("runner.py",), tests_failed=True, errors=("over 64KB",))


@dataclass
class _FakeStore:
    events: list[EpisodicEvent] = field(default_factory=list)
    raises: bool = False

    async def save_episode_entity(self, event: EpisodicEvent) -> None:
        self.events.append(event)
        if self.raises:
            raise RuntimeError("store down")


@dataclass
class _FakeDistiller:
    episodes: tuple[WorkEpisode, ...] = ()
    raises: bool = False
    seen: list[tuple[str, SessionKeyFacts, WorkOutcome]] = field(default_factory=list)

    async def distill(
        self, task: str, facts: SessionKeyFacts, outcome: WorkOutcome
    ) -> Sequence[WorkEpisode]:
        self.seen.append((task, facts, outcome))
        if self.raises:
            raise RuntimeError("distiller down")
        return self.episodes


@dataclass
class _Clock:
    def now(self) -> datetime:
        return _NOW


def _recorder(distiller: WorkJournalDistiller, store: _FakeStore) -> DistillingWorkJournalRecorder:
    return DistillingWorkJournalRecorder(distiller=distiller, store=store, clock=_Clock())


async def test_writes_distilled_episodes_as_work_events() -> None:
    distiller = _FakeDistiller(episodes=(WorkEpisode("я починил стрим — позеленело"),))
    store = _FakeStore()

    await _recorder(distiller, store).record_session(
        "почини стрим", _FACTS, WorkOutcome.FINISHED, sender_id=_OWNER
    )

    assert len(store.events) == 1
    event = store.events[0]
    assert event.event_type == "work"
    assert event.content == "я починил стрим — позеленело"
    assert "work" in event.tags
    assert "dev" in event.tags
    assert any(tag.startswith("actor:") for tag in event.tags)
    assert event.visibility == VISIBILITY_OWNER_PRIVATE
    assert event.sender_id == _OWNER


async def test_passes_facts_and_outcome_to_distiller() -> None:
    distiller = _FakeDistiller(episodes=(WorkEpisode("я доделал"),))
    await _recorder(distiller, _FakeStore()).record_session(
        "задача", _FACTS, WorkOutcome.FAILED, sender_id=None
    )
    assert distiller.seen == [("задача", _FACTS, WorkOutcome.FAILED)]


async def test_empty_snapshot_is_skipped_no_distill_no_write() -> None:
    distiller = _FakeDistiller(episodes=(WorkEpisode("nope"),))
    store = _FakeStore()

    await _recorder(distiller, store).record_session(
        "задача", SessionKeyFacts(), WorkOutcome.FINISHED, sender_id=_OWNER
    )

    assert store.events == []
    assert distiller.seen == []  # distiller never consulted for an empty session


async def test_no_episodes_writes_nothing() -> None:
    store = _FakeStore()
    await _recorder(_FakeDistiller(episodes=()), store).record_session(
        "задача", _FACTS, WorkOutcome.FINISHED, sender_id=_OWNER
    )
    assert store.events == []


async def test_raising_distiller_never_raises() -> None:
    store = _FakeStore()
    # A distiller fault must be swallowed — the coding session must complete regardless.
    await _recorder(_FakeDistiller(raises=True), store).record_session(
        "задача", _FACTS, WorkOutcome.FINISHED, sender_id=_OWNER
    )
    assert store.events == []


async def test_raising_store_never_raises() -> None:
    distiller = _FakeDistiller(episodes=(WorkEpisode("я доделал"),))
    # A store fault mid-write must be swallowed too (best-effort side channel).
    await _recorder(distiller, _FakeStore(raises=True)).record_session(
        "задача", _FACTS, WorkOutcome.FINISHED, sender_id=_OWNER
    )


async def test_noop_recorder_writes_nothing() -> None:
    store = _FakeStore()
    distiller = _FakeDistiller(episodes=(WorkEpisode("nope"),))
    recorder = NoOpWorkJournalRecorder()

    await recorder.record_session("задача", _FACTS, WorkOutcome.FINISHED, sender_id=_OWNER)

    assert store.events == []
    assert distiller.seen == []
