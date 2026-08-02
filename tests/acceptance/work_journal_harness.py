# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary harness for the work-journal scenarios (BOB-087 Срез B).

Drives Bob's dev-session → work-journal WRITE-and-READ path through REAL boundaries — the
only fake is the LLM (the distiller's Tier-0 call), mirroring how the other coding harnesses
fake the runner/model:

1. the raw claude stream-json firehose a session emits is folded by the REAL
   :class:`~bob.coding.work_facts.WorkFactsAccumulator` into a BOUNDED
   :class:`~bob.coding.work_facts.SessionKeyFacts` snapshot (files/tests/errors, capped) —
   NOT the firehose itself;
2. the REAL :class:`~bob.coding.usecases.work_journal_recorder.DistillingWorkJournalRecorder`
   distils that snapshot via the REAL :class:`~bob.coding.usecases.distill_work_journal.
   Tier0WorkJournalDistiller` (a fake Tier-0 provider stands in for the local model) and
   deposits the first-person episodes into a REAL SQLite memory store as ``work`` events;
3. the deposited memory is read back through the REAL keyword recall
   (:class:`~bob.memory.adapters.fts_recall.Fts5MemoryRecall`) and the REAL disclosure gate
   (:func:`~bob.social.disclosure.filter_surfaceable`), so what the OWNER vs a GUEST would
   observably recall is exercised, never private store internals.

When the ``memory.work_journal`` flag is OFF the harness wires the
:class:`~bob.coding.usecases.work_journal_recorder.NoOpWorkJournalRecorder`, so the store
stays byte-identical to today (nothing written, nothing recalled).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.usecases.work_journal_recorder import (
    DistillingWorkJournalRecorder,
    NoOpWorkJournalRecorder,
)
from bob.coding.work_facts import WorkFactsAccumulator, WorkOutcome
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.work_journal import WORK_EVENT_TYPE
from bob.social.disclosure import filter_surfaceable
from bob.social.interlocutor import Trust

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

OWNER_ID = 27468732

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class _FixedClock:
    """A frozen clock — the write timestamp is irrelevant to the read behaviour."""

    def now(self) -> datetime:
        return _NOW


class _FakeTier0Provider:
    """Stands in for the local Tier-0 model: returns a fixed multi-line answer.

    The distiller's ONLY external boundary. The lines it returns are the model's
    first-person recollection of the session; the harness then exercises the REAL parser,
    recorder, store, recall and disclosure gate around it.
    """

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        return self._answer


@dataclass(slots=True)
class WorkJournalOutcome:
    """What Bob would OBSERVABLY carry away from a dev session.

    ``owner_recall`` / ``guest_recall`` — the work-memory contents that surface to the OWNER
    (trusted) vs a GUEST (untrusted) through the real recall + disclosure gate;
    ``recalled_categories`` — the ``event_type`` domain each surfaced item lives on (so a work
    memory is observably on the ``work`` seam, not mixed into ``self_action``/personal);
    ``stored_work`` — the ``work`` episodes actually deposited (content + provenance tags);
    ``raw_event_count`` — how many firehose events fed the session (to contrast the bounded
    episode count against the flood).
    """

    owner_recall: tuple[str, ...] = ()
    guest_recall: tuple[str, ...] = ()
    recalled_categories: tuple[str, ...] = ()
    stored_work: tuple[Mapping[str, object], ...] = ()
    raw_event_count: int = 0


async def run_dev_session(
    tmp_path: Path,
    *,
    journal_enabled: bool,
    events: Sequence[Mapping[str, object]],
    task: str,
    outcome: WorkOutcome,
    model_reply: str,
    question: str,
) -> WorkJournalOutcome:
    """Fold ``events`` into facts, record the work journal, then read it back.

    With ``journal_enabled`` the real distilling recorder writes the distilled first-person
    episodes as owner-private ``work`` events; without it the no-op recorder writes nothing.
    ``question`` drives the real keyword recall so a stored episode must EARN its place by
    matching. Returns the observable owner-vs-guest recall + the deposited provenance.
    """
    accumulator = WorkFactsAccumulator()
    for event in events:
        accumulator.observe(event)
    facts = accumulator.snapshot()

    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    try:
        if journal_enabled:
            provider = _FakeTier0Provider(model_reply)
            distiller = Tier0WorkJournalDistiller(
                router=LLMRouter(providers={0: provider})
            )
            recorder: DistillingWorkJournalRecorder | NoOpWorkJournalRecorder = (
                DistillingWorkJournalRecorder(
                    distiller=distiller, store=repo, clock=_FixedClock()
                )
            )
        else:
            recorder = NoOpWorkJournalRecorder()

        await recorder.record_session(task, facts, outcome, sender_id=OWNER_ID)

        raw = await Fts5MemoryRecall(repo).recall(question, k=8)
        owner = filter_surfaceable(raw, Trust.TRUSTED)
        guest = filter_surfaceable(raw, Trust.GUEST)
        stored = [
            row
            for row in await repo.load_episodes(limit=50)
            if row.get("event_type") == WORK_EVENT_TYPE
        ]
    finally:
        await repo.close()

    return WorkJournalOutcome(
        owner_recall=tuple(str(item.get("content", "")) for item in owner),
        guest_recall=tuple(str(item.get("content", "")) for item in guest),
        recalled_categories=tuple(str(item.get("category", "")) for item in owner),
        stored_work=tuple(stored),
        raw_event_count=len(events),
    )
