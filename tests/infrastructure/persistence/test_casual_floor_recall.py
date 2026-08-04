# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for :class:`CasualFloorRecall` — the CASUAL floor on secondary recall (BOB-087.C8).

The register-aware down-weight of Срез C guarded ONLY the primary reply-recall. This
decorator holds every SECONDARY recall channel (the grounded-addon callback, the two memory
tool capabilities, the proactive seed) at the conservative CASUAL floor by construction: it
over-fetches, lets the SAME pure core (``register_ranked`` in CASUAL) mute Bob's ``work``
episodes, and truncates back to the caller's ``k``. Muted — never cut (сквозной Боб): a
work-only pool still comes back, in its original order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.memory.adapters.casual_floor_recall import (
    SECONDARY_OVERFETCH_FACTOR,
    CasualFloorRecall,
)
from bob.memory.work_journal import WORK_EVENT_TYPE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.memory.ports import Recalled

_CHAT_EVENT_TYPE = "message"


class _SpyRecall:
    """A fake :class:`~bob.memory.ports.MemoryRecall` that records what it was asked for."""

    def __init__(self, hits: Sequence[Recalled]) -> None:
        self._hits = list(hits)
        self.calls: list[tuple[str, int, bool]] = []

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        self.calls.append((query, k, surface_old))
        return self._hits[:k]


def _work(content: str) -> Recalled:
    return {"content": content, "category": WORK_EVENT_TYPE, "score": -1.0}


def _chat(content: str) -> Recalled:
    return {"content": content, "category": _CHAT_EVENT_TYPE, "score": -1.0}


def _contents(hits: Sequence[Recalled]) -> tuple[str, ...]:
    return tuple(str(hit["content"]) for hit in hits)


async def test_work_is_muted_out_of_the_slots_by_deeper_chat() -> None:
    # The heart: a work episode ranked FIRST loses its slot to ordinary chat that sat
    # deeper in the over-fetched pool — the same teeth as the primary path.
    inner = _SpyRecall([_work("я попросил GUPPI починить лимит"), _chat("гуляли в парке")])
    floored = CasualFloorRecall(inner)

    hits = await floored.recall("что нового", k=1)

    assert _contents(hits) == ("гуляли в парке",)


async def test_work_still_surfaces_when_there_is_nothing_else() -> None:
    # Сквозной Боб: attenuation NEVER cuts. A work-only pool comes back — in its
    # original best-first order (the mute is uniform, so it cannot reshuffle work).
    inner = _SpyRecall([_work("починил раннер"), _work("позеленели тесты")])
    floored = CasualFloorRecall(inner)

    hits = await floored.recall("что нового", k=2)

    assert _contents(hits) == ("починил раннер", "позеленели тесты")


async def test_pool_without_work_is_the_plain_top_k() -> None:
    inner = _SpyRecall([_chat("первое"), _chat("второе"), _chat("третье")])
    floored = CasualFloorRecall(inner)

    hits = await floored.recall("что нового", k=2)

    assert _contents(hits) == ("первое", "второе")


async def test_overfetches_so_the_mute_has_something_to_promote() -> None:
    inner = _SpyRecall([_chat("что-то")])
    floored = CasualFloorRecall(inner)

    await floored.recall("что нового", k=5)

    assert inner.calls == [("что нового", 5 * SECONDARY_OVERFETCH_FACTOR, False)]


async def test_surface_old_opt_in_is_passed_through() -> None:
    inner = _SpyRecall([_chat("старое, но родное")])
    floored = CasualFloorRecall(inner)

    await floored.recall("что нового", k=1, surface_old=True)

    assert inner.calls == [("что нового", SECONDARY_OVERFETCH_FACTOR, True)]


async def test_non_positive_k_stays_an_empty_no_op() -> None:
    inner = _SpyRecall([_chat("что-то")])
    floored = CasualFloorRecall(inner)

    assert await floored.recall("что нового", k=0) == ()
    assert inner.calls == []
