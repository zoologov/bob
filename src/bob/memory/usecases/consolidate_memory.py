# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=application

"""ConsolidateMemory — the rare, non-destructive digest step (BOB-021).

Hooked onto the heartbeat reflect tick (a slow cadence), this lets Bob's episodic
archive *mature* without ever forgetting. Each run:

1. **Select OLD, un-consolidated, non-digest episodes** — a batch (size from
   config) of episodes older than the configured age threshold that have not yet
   been folded into a digest and are not themselves digests. The persistence seam
   enforces this predicate, so a digest is never re-digested.
2. **Summarise on Tier 0** — a cheap, LOCAL router call (privacy: memory content
   never leaves the machine) with a prompt that asks Bob to compress the window into
   one digest while *preserving facts, names, and decisions*.
3. **Write the digest** — as a normal ``episodic_log`` row (``event_type='digest'``),
   embedded on write (BOB-011), so the hybrid recall surfaces it the same as any
   episode. Provenance (the ts-range of its sources) is carried in the digest text.
4. **Flag the sources** ``consolidated=1`` — non-destructive: the originals are kept,
   only marked, so they drop out of future selection.

**Idempotent:** only un-consolidated, non-digest episodes are eligible; a re-run with
nothing eligible is a clean no-op (no duplicate digest). **Bounded:** age/batch
thresholds come from config with conservative defaults. Everything is injected —
store, router, clock — so the step holds no globals and is deterministic on fakes.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.personality.language import DEFAULT_LANGUAGE, language_directive

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from bob.domain.ports import Clock

logger = logging.getLogger(__name__)

# Conservative defaults (overridable via ``memory.consolidation.*``): only fold
# episodes at least two weeks old, a modest batch per rare tick.
_DEFAULT_MAX_AGE_DAYS = 14.0
_DEFAULT_BATCH_SIZE = 50

_SECONDS_PER_DAY = 86_400.0

# The Tier-0 summarisation prompt: compress the window into ONE digest while keeping
# the load-bearing detail — facts, names, decisions. It must read as Bob's own memory,
# not a meta description, so it stays recallable alongside raw episodes.
_DIGEST_PROMPT = (
    "Сожми приведённые ниже старые записи памяти в один короткий дайджест. "
    "Обязательно сохрани факты, имена и принятые решения. Пиши от первого лица "
    "как сжатое воспоминание, без преамбулы и пояснений."
)


class _Router(Protocol):
    """The narrow router seam the digest needs: run one LLM request, get text back.

    Structurally satisfied by :class:`~bob.application.router.LLMRouter` (which app.py
    injects); depending on the contract rather than the concrete router keeps the step
    testable on a cheap fake.
    """

    async def run(self, request: LLMRequest) -> str: ...


class ConsolidationStore(Protocol):
    """The persistence seam ConsolidateMemory drives (BOB-021).

    Realised by :class:`~bob.memory.adapters.sqlite_memory_repo.SqliteMemoryRepo`:
    select OLD un-consolidated non-digest episodes, write a digest episode (embedded on
    write), and flag the sources — non-destructively.
    """

    async def select_consolidatable_episodes(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[Mapping[str, object]]:
        """Return up to ``limit`` OLD, un-consolidated, non-digest episodes (oldest first)."""
        ...

    async def save_digest(self, digest: Mapping[str, object]) -> None:
        """Write a digest as an ``episodic_log`` row (event_type='digest'); embed it."""
        ...

    async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
        """Flag the given source episodes as folded into a digest (non-destructive)."""
        ...


class ConsolidateMemory:
    """Rarely fold OLD episodes into a digest — non-destructive, idempotent, bounded."""

    def __init__(
        self,
        *,
        store: ConsolidationStore,
        router: _Router,
        clock: Clock,
        max_age_days: float = _DEFAULT_MAX_AGE_DAYS,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._store = store
        self._router = router
        self._clock = clock
        self._max_age_days = max(0.0, max_age_days)
        self._batch_size = max(0, batch_size)
        self._language = language

    async def run(self) -> None:
        """Run one consolidation step: fold an eligible batch into a digest (or no-op)."""
        if self._batch_size == 0:
            return
        cutoff = self._cutoff()
        episodes = await self._store.select_consolidatable_episodes(
            older_than=cutoff, limit=self._batch_size
        )
        if not episodes:
            return  # nothing eligible: a clean, idempotent no-op.
        summary = await self._summarise(episodes)
        if not summary.strip():
            # Tier 0 yielded nothing usable: skip without flagging so a later tick
            # can retry — never lose the originals to an empty digest.
            logger.debug("consolidation produced an empty digest; skipping this batch")
            return
        await self._store.save_digest(self._digest_row(summary, episodes))
        await self._store.mark_consolidated(_episode_ids(episodes))
        logger.debug("consolidated %d episodes into a digest", len(episodes))

    def _cutoff(self) -> datetime:
        """The age boundary: episodes strictly older than this are eligible."""
        return self._clock.now() - timedelta(days=self._max_age_days)

    async def _summarise(self, episodes: Sequence[Mapping[str, object]]) -> str:
        """Compress the episode window into one digest on Tier 0 (local, private)."""
        material = "\n- ".join(str(e["content"]) for e in episodes)
        return await self._router.run(
            LLMRequest(
                task_type=TaskType.REFLECT,
                messages=[{"role": "system", "content": self._localised(_DIGEST_PROMPT)}],
                private_context=f"Старые записи:\n- {material}",
            )
        )

    @staticmethod
    def _digest_row(
        summary: str, episodes: Sequence[Mapping[str, object]]
    ) -> dict[str, object]:
        """Build the digest episode row, stamping the source ts-range as provenance."""
        timestamps = sorted(str(e["ts"]) for e in episodes)
        provenance = f"{timestamps[0]}..{timestamps[-1]}"
        return {
            "ts": timestamps[-1],
            "content": summary.strip(),
            "tags": "consolidation",
            "mood_snapshot": provenance,
        }

    def _localised(self, prompt: str) -> str:
        """Prepend the persona language directive to a self-generated prompt (BOB-012)."""
        return f"{language_directive(self._language)}\n{prompt}"


def _episode_ids(episodes: Sequence[Mapping[str, object]]) -> list[int]:
    """Extract the integer ids of the source episodes for flagging."""
    return [int(str(e["id"])) for e in episodes]
