# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for DedupFacts — the rare, conservative fact-merge step (BOB-021).

On the reflect tick Bob merges near-duplicate semantic facts: facts whose
embeddings sit above a CONSERVATIVE cosine threshold are clustered, a canonical
(newest, then longest) is chosen, and the others are flagged ``superseded_by`` the
canonical — non-destructive (the rows stay, with provenance) and idempotent
(already-superseded facts are excluded, so a re-run with nothing to merge is a
no-op). Covered here on fakes (no network): near-duplicates merge to one canonical;
dissimilar facts are NEVER merged; idempotency; non-destructiveness; canonical
selection (newest, then longest); config-gating (a zero-threshold/empty archive
no-op); local-only (a controllable in-test embedder, never a network call).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.memory.usecases.dedup_facts import DedupFacts

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class StubEmbedder:
    """Deterministic embedder driven by an explicit content->vector table.

    Realises :class:`bob.domain.ports.Embedder`. Unknown text maps to a fixed
    orthogonal default so unrelated facts stay far apart in cosine space.
    """

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._table.get(text, [0.0, 0.0, 1.0]) for text in texts]


class FakeDedupStore:
    """In-memory double for the dedup persistence seam.

    Holds facts as {id: {id, ts, content}} and excludes superseded facts from
    ``select_active_facts`` (mirroring the SQL predicate) so idempotency is tested
    honestly. ``supersede_facts`` records {duplicate_id: canonical_id}.
    """

    def __init__(self, facts: list[dict[str, object]]) -> None:
        self.facts = {int(str(f["id"])): f for f in facts}
        self.superseded: dict[int, int] = {}

    async def select_active_facts(self) -> Sequence[Mapping[str, object]]:
        return [f for fid, f in self.facts.items() if fid not in self.superseded]

    async def supersede_facts(self, mapping: Mapping[int, int]) -> None:
        self.superseded.update(mapping)


def _fact(fid: int, content: str, *, day: int = 18) -> dict[str, object]:
    return {
        "id": fid,
        "ts": datetime(2026, 6, day, 9, 0, tzinfo=UTC).isoformat(),
        "content": content,
    }


def _dedup(
    store: FakeDedupStore,
    embedder: StubEmbedder,
    *,
    threshold: float = 0.92,
    batch_size: int = 200,
) -> DedupFacts:
    return DedupFacts(
        store=store,
        embedder=embedder,
        clock=FakeClock(_NOW),
        threshold=threshold,
        batch_size=batch_size,
    )


async def test_near_duplicates_merge_to_one_canonical() -> None:
    # Arrange: two near-identical facts (cosine ~1.0) and an unrelated one.
    store = FakeDedupStore(
        [
            _fact(1, "любит зелёный чай", day=10),
            _fact(2, "обожает зелёный чай", day=12),
            _fact(3, "живёт в Москве", day=11),
        ]
    )
    embedder = StubEmbedder(
        {
            "любит зелёный чай": [1.0, 0.0, 0.0],
            "обожает зелёный чай": [0.999, 0.044, 0.0],
            "живёт в Москве": [0.0, 1.0, 0.0],
        }
    )

    # Act
    await _dedup(store, embedder).run()

    # Assert: the older duplicate is superseded into the newer canonical (id 2);
    # the unrelated fact is untouched.
    assert store.superseded == {1: 2}


async def test_dissimilar_facts_are_never_merged() -> None:
    # Arrange: two facts that are clearly different (orthogonal vectors).
    store = FakeDedupStore(
        [_fact(1, "любит чай"), _fact(2, "ненавидит кофе")]
    )
    embedder = StubEmbedder(
        {"любит чай": [1.0, 0.0, 0.0], "ненавидит кофе": [0.0, 1.0, 0.0]}
    )

    # Act
    await _dedup(store, embedder).run()

    # Assert: NO false merge — conservative threshold protects distinct facts.
    assert store.superseded == {}


async def test_just_below_threshold_is_not_merged() -> None:
    # Arrange: a pair whose cosine sits just under the conservative threshold.
    store = FakeDedupStore([_fact(1, "A"), _fact(2, "B")])
    # cosine([1,0], [cos t, sin t]) = cos t; pick ~0.90 < 0.92.
    embedder = StubEmbedder({"A": [1.0, 0.0], "B": [0.90, 0.4359]})

    # Act
    await _dedup(store, embedder, threshold=0.92).run()

    # Assert: below threshold -> not merged.
    assert store.superseded == {}


async def test_second_run_is_a_noop() -> None:
    # Arrange: a near-duplicate pair, merged on the first run.
    store = FakeDedupStore(
        [_fact(1, "x", day=10), _fact(2, "x2", day=12)]
    )
    embedder = StubEmbedder({"x": [1.0, 0.0], "x2": [1.0, 0.0]})
    usecase = _dedup(store, embedder)
    await usecase.run()
    first = dict(store.superseded)

    # Act: a second run — the already-superseded fact is excluded.
    await usecase.run()

    # Assert: idempotent — no re-merge, mapping unchanged.
    assert store.superseded == first == {1: 2}


async def test_canonical_is_the_newest_then_longest() -> None:
    # Arrange: three near-identical facts; ids/ts/length chosen so the newest wins,
    # and among same-day facts the longest content wins.
    store = FakeDedupStore(
        [
            _fact(1, "чай", day=10),  # oldest, short
            _fact(2, "зелёный чай подробно", day=20),  # newest, long -> canonical
            _fact(3, "зелёный чай", day=20),  # same newest day, shorter
        ]
    )
    same = [1.0, 0.0]
    embedder = StubEmbedder(
        {"чай": same, "зелёный чай подробно": same, "зелёный чай": same}
    )

    # Act
    await _dedup(store, embedder).run()

    # Assert: id 2 is canonical (newest day, longest among that day); 1 and 3 merge.
    assert store.superseded == {1: 2, 3: 2}


async def test_non_destructive_keeps_all_rows() -> None:
    # Arrange
    store = FakeDedupStore([_fact(1, "a", day=10), _fact(2, "a2", day=12)])
    embedder = StubEmbedder({"a": [1.0, 0.0], "a2": [1.0, 0.0]})

    # Act
    await _dedup(store, embedder).run()

    # Assert: both rows still present in the store (only flagged, never removed).
    assert set(store.facts) == {1, 2}


async def test_empty_archive_is_a_noop() -> None:
    # Arrange
    store = FakeDedupStore([])
    embedder = StubEmbedder({})

    # Act
    await _dedup(store, embedder).run()

    # Assert: nothing to do — no embedding call, no supersession.
    assert embedder.calls == 0
    assert store.superseded == {}


async def test_single_fact_is_a_noop() -> None:
    # Arrange: one fact cannot have a duplicate.
    store = FakeDedupStore([_fact(1, "lonely")])
    embedder = StubEmbedder({"lonely": [1.0, 0.0]})

    # Act
    await _dedup(store, embedder).run()

    # Assert
    assert store.superseded == {}


async def test_zero_batch_is_a_noop() -> None:
    # Arrange: batch_size 0 disables the step (a no-op, no embedding).
    store = FakeDedupStore([_fact(1, "a", day=10), _fact(2, "a2", day=12)])
    embedder = StubEmbedder({"a": [1.0, 0.0], "a2": [1.0, 0.0]})

    # Act
    await _dedup(store, embedder, batch_size=0).run()

    # Assert
    assert embedder.calls == 0
    assert store.superseded == {}


def test_build_dedup_facts_is_config_gated_and_needs_an_embedder(tmp_path: Path) -> None:
    # The app builder returns None unless memory.dedup.enabled AND an embedder is wired
    # (off by default like consolidation; keyword-only memory cannot compute cosine).
    from bob.app import _build_dedup_facts  # noqa: PLC0415
    from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo  # noqa: PLC0415

    embedder = StubEmbedder({})
    clock = FakeClock(_NOW)
    store = SqliteMemoryRepo(tmp_path / "bob.db")

    # Disabled by default -> None.
    assert _build_dedup_facts({}, store=store, embedder=embedder, clock=clock) is None
    # Enabled but no embedder -> None (keyword-only memory).
    enabled: dict[str, object] = {"memory": {"dedup": {"enabled": True}}}
    assert _build_dedup_facts(enabled, store=store, embedder=None, clock=clock) is None
    # Enabled with an embedder -> a DedupFacts.
    built = _build_dedup_facts(enabled, store=store, embedder=embedder, clock=clock)
    assert isinstance(built, DedupFacts)


async def test_transitive_cluster_merges_into_one_canonical() -> None:
    # Arrange: three facts where A~B and B~C (single-linkage) but A and C are not
    # directly above threshold — the cluster still collapses to one canonical.
    store = FakeDedupStore(
        [
            _fact(1, "A", day=10),
            _fact(2, "B", day=12),
            _fact(3, "C", day=20),  # newest -> canonical
        ]
    )
    embedder = StubEmbedder(
        {
            "A": [1.0, 0.0],
            "B": [0.97, 0.243],
            "C": [0.90, 0.436],  # A·C = 0.90 < 0.92, B·C ~ 0.978 >= 0.92
        }
    )

    # Act
    await _dedup(store, embedder, threshold=0.92).run()

    # Assert: all three collapse into the single newest canonical (id 3).
    assert store.superseded == {1: 3, 2: 3}
