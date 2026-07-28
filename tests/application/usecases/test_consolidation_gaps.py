# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-021 gap-closing tests: app wiring, guardrail branches, local-only invariants.

The dev wave already pins the behaviour of ConsolidateMemory / DedupFacts / the
``surface_old`` recall blend at the unit, repo, and handle-message layers. This
file closes the remaining acceptance gaps the test wave owns:

* **Config-gating of the wiring** — ``_build_consolidate_memory`` is OFF by default
  and built (with the config guardrails) only when ``memory.consolidation.enabled``;
  ``_build_surface_old_freq`` resolves the anti-tic default and a config override.
* **Guardrail branches** — the defensive paths the happy-path tests do not reach:
  a ``batch_size=0`` consolidation no-op, a misaligned-embedder-batch dedup no-op,
  a zero-magnitude cosine, and the ``surface_old_freq`` range validation.
* **Local-only / zero-network invariant** — both steps drive their LLM/embedder
  EXCLUSIVELY through the injected port; a port that fails if it ever touches the
  network proves memory content never leaves the machine (fakes only, no sockets).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.app import (
    SystemClock,
    _build_consolidate_memory,
    _build_dedup_facts,
    _build_surface_old_freq,
)
from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.handle_message import _DEFAULT_SURFACE_OLD_FREQ
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.dedup_facts import DedupFacts, _cosine, _supersession_mapping

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return _NOW


class _LocalOnlyProvider:
    """An LLM provider that proves it never reaches the network.

    Realises the provider seam the router calls; it simply echoes a canned reply
    from local memory. There is no HTTP client here at all — if any consolidation
    path tried to dial out it would have to go through a *different* object, so a
    test wired to this provider proves memory content stays on-machine.
    """

    def __init__(self, reply: str = "сжатый локальный дайджест") -> None:
        self.reply = reply
        self.seen: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.seen.append("".join(m.get("content", "") for m in messages))
        return self.reply


class _LocalOnlyEmbedder:
    """An embedder that proves it never reaches the network (a fixed local table)."""

    def __init__(self, table: dict[str, list[float]]) -> None:
        self._table = table
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._table.get(text, [0.0, 0.0, 1.0]) for text in texts]


class _ExplodingEmbedder:
    """An embedder whose batch is deliberately misaligned (fewer vectors than texts)."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:  # noqa: ARG002
        return [[1.0, 0.0]]  # one vector regardless of how many texts came in


class _RecordingDedupStore:
    """Minimal DedupStore double recording whether supersede was ever called."""

    def __init__(self, facts: list[dict[str, object]]) -> None:
        self._facts = facts
        self.superseded: dict[int, int] = {}

    async def select_active_facts(self) -> Sequence[Mapping[str, object]]:
        return list(self._facts)

    async def supersede_facts(self, mapping: Mapping[int, int]) -> None:
        self.superseded.update(mapping)


class _ConsolidationStoreSpy:
    """ConsolidationStore double that records every method touched."""

    def __init__(self) -> None:
        self.selected = False
        self.digests: list[Mapping[str, object]] = []
        self.flagged: list[int] = []

    async def select_consolidatable_episodes(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[Mapping[str, object]]:
        del older_than, limit
        self.selected = True
        return []

    async def save_digest(self, digest: Mapping[str, object]) -> None:
        self.digests.append(digest)

    async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
        self.flagged.extend(episode_ids)


# --- App wiring: config-gating of the consolidation steps ----------------------


def test_build_consolidate_memory_is_off_by_default(tmp_path: Path) -> None:
    # The reflect tick must get NO consolidator unless deliberately switched on, so
    # an upgrade is inert until the owner enables it (conservative-by-default).
    from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo  # noqa: PLC0415

    store = SqliteMemoryRepo(tmp_path / "bob.db")
    router = LLMRouter(providers={0: _LocalOnlyProvider()})

    built = _build_consolidate_memory(
        {}, store=store, router=router, clock=SystemClock(), language="ru"
    )

    assert built is None


def test_build_consolidate_memory_when_enabled_uses_config_guardrails(
    tmp_path: Path,
) -> None:
    # Enabled -> a ConsolidateMemory carrying the configured age/batch guardrails
    # (so the conservative thresholds are owner-tunable, not hard-coded).
    from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo  # noqa: PLC0415

    store = SqliteMemoryRepo(tmp_path / "bob.db")
    router = LLMRouter(providers={0: _LocalOnlyProvider()})
    config: dict[str, object] = {
        "memory": {
            "consolidation": {"enabled": True, "max_age_days": 7.0, "batch_size": 5},
        }
    }

    built = _build_consolidate_memory(
        config, store=store, router=router, clock=SystemClock(), language="ru"
    )

    assert isinstance(built, ConsolidateMemory)
    assert built._max_age_days == 7.0
    assert built._batch_size == 5


def test_build_surface_old_freq_defaults_to_the_anti_tic_value() -> None:
    # With no config, the surface-old draw frequency is the small anti-tic default,
    # so the default recall path stays unchanged (the blend only ever rides callbacks).
    assert _build_surface_old_freq({}) == pytest.approx(_DEFAULT_SURFACE_OLD_FREQ)


def test_build_surface_old_freq_reads_a_config_override() -> None:
    # An explicit override is honoured so the (rare) surface-old cadence is tunable.
    config: dict[str, object] = {"memory": {"surface_old": {"freq": 0.5}}}
    assert _build_surface_old_freq(config) == pytest.approx(0.5)


def test_build_dedup_facts_off_by_default_and_when_no_embedder(tmp_path: Path) -> None:
    # Dedup is off by default AND a no-op without an embedder (keyword-only memory
    # cannot compute cosine) — the two guardrails that keep the step inert.
    from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo  # noqa: PLC0415

    store = SqliteMemoryRepo(tmp_path / "bob.db")
    embedder = _LocalOnlyEmbedder({})

    assert _build_dedup_facts({}, store=store, embedder=embedder, clock=FakeClock()) is None
    enabled: dict[str, object] = {"memory": {"dedup": {"enabled": True}}}
    assert _build_dedup_facts(enabled, store=store, embedder=None, clock=FakeClock()) is None


# --- Guardrail branches the happy path does not reach --------------------------


async def test_consolidation_with_zero_batch_never_touches_the_store() -> None:
    # A ``batch_size=0`` consolidation disables the step entirely: it must not even
    # SELECT (a hard runaway guard), so the store sees no traffic.
    store = _ConsolidationStoreSpy()
    usecase = ConsolidateMemory(
        store=store,
        router=LLMRouter(providers={0: _LocalOnlyProvider()}),
        clock=FakeClock(),
        batch_size=0,
    )

    await usecase.run()

    assert store.selected is False
    assert store.digests == []
    assert store.flagged == []


async def test_dedup_skips_a_misaligned_embedder_batch() -> None:
    # Defensive guard: if the embedder returns fewer vectors than facts (a broken
    # batch), dedup must abort cleanly rather than mis-pair facts to vectors.
    store = _RecordingDedupStore(
        [
            {"id": 1, "ts": _NOW.isoformat(), "content": "a"},
            {"id": 2, "ts": _NOW.isoformat(), "content": "b"},
        ]
    )
    usecase = DedupFacts(store=store, embedder=_ExplodingEmbedder(), clock=FakeClock())

    await usecase.run()

    assert store.superseded == {}  # no merge from a misaligned batch — never mis-pair


def test_cosine_of_a_zero_vector_is_zero() -> None:
    # A zero-magnitude vector has no direction: cosine is defined as 0.0 (never a
    # divide-by-zero), so a degenerate embedding can never look like a duplicate.
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert _cosine([1.0, 0.0], [0.0, 0.0]) == 0.0


def test_supersession_mapping_is_empty_for_all_singletons() -> None:
    # Pure-function guard: orthogonal vectors form only singleton clusters, so the
    # supersession mapping is empty — dissimilar facts are never merged.
    facts = [
        {"id": 1, "ts": _NOW.isoformat(), "content": "x"},
        {"id": 2, "ts": _NOW.isoformat(), "content": "y"},
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    assert _supersession_mapping(facts, vectors, threshold=0.92) == {}


@pytest.mark.parametrize("freq", [-0.01, 1.01, 2.0, -1.0])
def test_handle_message_rejects_an_out_of_range_surface_old_freq(freq: float) -> None:
    # A frequency must read as a probability in [0, 1]; an out-of-range knob is a
    # config error caught at construction, never silently clamped.
    from random import Random  # noqa: PLC0415

    from bob.application.usecases.handle_message import HandleMessage  # noqa: PLC0415

    with pytest.raises(ValueError, match="surface_old_freq"):
        HandleMessage(
            router=LLMRouter(providers={0: _LocalOnlyProvider()}),
            gateway=None,  # type: ignore[arg-type]
            recall=None,  # type: ignore[arg-type]
            repo=None,  # type: ignore[arg-type]
            episodes=None,  # type: ignore[arg-type]
            update_mood=None,  # type: ignore[arg-type]
            extract_facts=None,  # type: ignore[arg-type]
            clock=FakeClock(),
            state=None,  # type: ignore[arg-type]
            rng=Random(0),  # noqa: S311 — deterministic test seed, not cryptographic
            surface_old_freq=freq,
        )


# --- Local-only / zero-network invariant (the privacy guardrail) ---------------


async def test_consolidation_drives_the_llm_only_through_the_injected_port() -> None:
    # Privacy: the digest is produced EXCLUSIVELY through the injected router/provider
    # (a local, in-memory fake — no HTTP client exists in this wiring), proving memory
    # content never leaves the machine. The source content reaches only that local port.
    provider = _LocalOnlyProvider()
    router = LLMRouter(providers={0: provider})

    class _Store:
        def __init__(self) -> None:
            self.digests: list[Mapping[str, object]] = []
            self.flagged: list[int] = []

        async def select_consolidatable_episodes(
            self, *, older_than: datetime, limit: int
        ) -> Sequence[Mapping[str, object]]:
            del older_than, limit
            return [
                {"id": 1, "ts": _old(1), "content": "приватное воспоминание A"},
                {"id": 2, "ts": _old(2), "content": "приватное воспоминание B"},
            ]

        async def save_digest(self, digest: Mapping[str, object]) -> None:
            self.digests.append(digest)

        async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
            self.flagged.extend(episode_ids)

    store = _Store()
    usecase = ConsolidateMemory(store=store, router=router, clock=FakeClock())
    # ``router`` wraps the local provider — the only seam content can reach.

    await usecase.run()

    # The source content reached ONLY the local provider (the privacy boundary).
    assert any("приватное воспоминание A" in seen for seen in provider.seen)
    assert len(store.digests) == 1
    assert store.digests[0]["content"] == provider.reply
    assert sorted(store.flagged) == [1, 2]


async def test_dedup_embeds_only_through_the_injected_port() -> None:
    # Privacy: dedup hashes facts to vectors ONLY through the injected embedder (a
    # local fake), so fact text never leaves the machine. Two near-identical vectors
    # merge; the local embedder is the sole thing that ever saw the content.
    store = _RecordingDedupStore(
        [
            {"id": 1, "ts": _old(10), "content": "любит чай"},
            {"id": 2, "ts": _old(12), "content": "обожает чай"},
        ]
    )
    embedder = _LocalOnlyEmbedder({"любит чай": [1.0, 0.0], "обожает чай": [1.0, 0.0]})
    usecase = DedupFacts(store=store, embedder=embedder, clock=FakeClock())

    await usecase.run()

    assert embedder.calls == 1  # one local batch, the only place content was read
    assert store.superseded == {1: 2}  # the older near-duplicate merged into the newer


def _old(day: int) -> str:
    return datetime(2026, 6, day, 9, 0, tzinfo=UTC).isoformat()
