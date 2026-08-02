# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the register-recall RANK pipeline — the teeth of the down-weight (BOB-087.C2).

C1 (:mod:`bob.memory.register`) gives the pure ORDER-PRESERVING attenuation; on its own,
attenuating a pool that is already the top display-k cannot evict a work episode (there is
nothing below it to promote). The teeth come from
:func:`bob.memory.register_pipeline.register_ranked`: it establishes a higher-is-better
positional relevance over an OVER-FETCHED pool, lets C1 mute the work episodes, RE-SORTS by
that relevance and truncates to display-k — so in CASUAL a work episode really does drop out
of the final slots while a non-work item rises from deeper in the pool. In DEV the pipeline
is the identity truncation (recall unchanged, original items preserved).
"""

from __future__ import annotations

from bob.memory.register import Register
from bob.memory.register_pipeline import pool_has_work, register_ranked
from bob.memory.work_journal import WORK_EVENT_TYPE


def _work(content: str) -> dict[str, object]:
    return {"content": content, "category": WORK_EVENT_TYPE}


def _chat(content: str) -> dict[str, object]:
    return {"content": content, "category": "personal"}


def _contents(items: tuple[object, ...]) -> list[str]:
    return [str(item["content"]) for item in items]  # type: ignore[index]


# --- register_ranked: CASUAL evicts work from the final slots (teeth) --------


def test_casual_evicts_work_from_final_slots() -> None:
    # Best-first over-fetched pool: two work episodes rank top, but deeper non-work
    # items exist. In CASUAL the muted work must be pushed OUT of the top-3.
    pool = (
        _work("я поднял лимит в раннере"),
        _work("GUPPI починил стример"),
        _chat("любит кофе"),
        _chat("гуляли в парке"),
        _chat("смотрели кино"),
    )
    ranked = register_ranked(pool, Register.CASUAL, display_k=3)
    assert _contents(ranked) == ["любит кофе", "гуляли в парке", "смотрели кино"]


def test_casual_surfaces_a_strong_work_match_when_chat_cannot_fill_slots() -> None:
    # сквозной Боб: when there is not enough non-work to fill display-k, the strongest
    # work episode still surfaces (muted, never cut).
    # Two work episodes rank top, one non-work below, but only TWO display slots: the
    # non-work rises and the single remaining slot goes to the STRONGER work episode.
    pool = (
        _work("я поднял лимит в раннере"),
        _work("GUPPI починил стример"),
        _chat("любит кофе"),
    )
    ranked = register_ranked(pool, Register.CASUAL, display_k=2)
    contents = _contents(ranked)
    assert "любит кофе" in contents
    # Exactly one work episode fills the remaining slot (the stronger, best-ranked one).
    assert contents.count("я поднял лимит в раннере") == 1
    assert "GUPPI починил стример" not in contents


def test_casual_leaves_a_pure_chat_pool_in_recall_order() -> None:
    pool = (_chat("a"), _chat("b"), _chat("c"), _chat("d"))
    ranked = register_ranked(pool, Register.CASUAL, display_k=3)
    assert _contents(ranked) == ["a", "b", "c"]


# --- register_ranked: DEV is identity truncation -----------------------------


def test_dev_is_identity_truncation_preserving_items() -> None:
    pool = (
        _work("я поднял лимит в раннере"),
        _work("GUPPI починил стример"),
        _chat("любит кофе"),
        _chat("гуляли в парке"),
    )
    ranked = register_ranked(pool, Register.DEV, display_k=3)
    # Best-first order preserved AND the item objects are untouched (no re-scoring).
    assert list(ranked) == list(pool[:3])
    assert ranked[0] is pool[0]


def test_ranked_truncates_to_display_k() -> None:
    pool = tuple(_chat(str(i)) for i in range(10))
    assert len(register_ranked(pool, Register.CASUAL, display_k=5)) == 5
    assert len(register_ranked(pool, Register.DEV, display_k=5)) == 5


def test_ranked_empty_pool_is_empty() -> None:
    assert register_ranked((), Register.CASUAL, display_k=5) == ()
    assert register_ranked((), Register.DEV, display_k=5) == ()


# --- pool_has_work: the Tier-0 optimisation gate -----------------------------


def test_pool_has_work_true_when_a_work_episode_present() -> None:
    assert pool_has_work((_chat("a"), _work("b"))) is True


def test_pool_has_work_true_by_provenance_tag() -> None:
    tagged = {"content": "x", "category": "episodic", "tags": ("dev", "actor:bob")}
    assert pool_has_work((tagged,)) is True


def test_pool_has_work_false_for_pure_chat() -> None:
    assert pool_has_work((_chat("a"), _chat("b"))) is False


def test_pool_has_work_false_for_empty_pool() -> None:
    assert pool_has_work(()) is False
