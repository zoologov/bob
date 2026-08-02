# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for register-aware recall — the pure down-weight core (BOB-087.C1).

Mirrors :mod:`bob.social.disclosure`: a pure, I/O-free predicate/weight
(:func:`may_recall_in_register`) plus its order-preserving pipeline filter
(:func:`filter_by_register`). In a CASUAL register Bob's ``work`` dev episodes are
MUTED (their relevance score is attenuated) so they rarely win a recall slot, yet are
never cut — сквозной Боб: a strong match can still surface one. In a DEV register recall
is byte-identical (the identity path, like a TRUSTED interlocutor in disclosure).
"""

from __future__ import annotations

from bob.memory.register import (
    CASUAL_WORK_WEIGHT,
    RECALL_WEIGHT_FULL,
    Register,
    filter_by_register,
    may_recall_in_register,
)
from bob.memory.work_journal import WORK_EVENT_TYPE

# --- may_recall_in_register: the pure weight ---------------------------------


def test_work_episode_in_casual_is_down_weighted() -> None:
    weight = may_recall_in_register(
        category=WORK_EVENT_TYPE, tags=(), register=Register.CASUAL
    )
    assert weight == CASUAL_WORK_WEIGHT
    assert 0.0 < weight < RECALL_WEIGHT_FULL  # muted, never cut


def test_work_episode_by_tag_in_casual_is_down_weighted() -> None:
    # No work category, but the provenance tag marks it a work episode.
    weight = may_recall_in_register(
        category="episodic", tags=("dev", "actor:bob"), register=Register.CASUAL
    )
    assert weight == CASUAL_WORK_WEIGHT


def test_work_episode_in_dev_keeps_full_weight() -> None:
    weight = may_recall_in_register(
        category=WORK_EVENT_TYPE, tags=("work",), register=Register.DEV
    )
    assert weight == RECALL_WEIGHT_FULL


def test_non_work_memory_keeps_full_weight_in_casual() -> None:
    weight = may_recall_in_register(
        category="message", tags=("chit-chat",), register=Register.CASUAL
    )
    assert weight == RECALL_WEIGHT_FULL


def test_work_category_match_is_case_insensitive() -> None:
    weight = may_recall_in_register(
        category="WORK", tags=(), register=Register.CASUAL
    )
    assert weight == CASUAL_WORK_WEIGHT


def test_missing_category_and_tags_is_non_work() -> None:
    weight = may_recall_in_register(
        category=None, tags=None, register=Register.CASUAL
    )
    assert weight == RECALL_WEIGHT_FULL


# --- filter_by_register: the order-preserving pipeline -----------------------


def _work(score: float) -> dict[str, object]:
    return {"content": "я попросил GUPPI…", "category": WORK_EVENT_TYPE, "score": score}


def _chat(score: float) -> dict[str, object]:
    return {"content": "как дела?", "category": "message", "score": score}


def test_dev_register_is_byte_identical() -> None:
    recalled = (_work(0.9), _chat(0.8))
    result = filter_by_register(recalled, Register.DEV)
    assert result == recalled
    # Identity path: the very same item objects pass through untouched.
    assert all(a is b for a, b in zip(result, recalled, strict=True))


def test_casual_attenuates_work_score_but_keeps_it() -> None:
    recalled = (_work(1.0),)
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item["score"] == 1.0 * CASUAL_WORK_WEIGHT
    assert item["content"] == "я попросил GUPPI…"  # not cut, content intact
    assert item["category"] == WORK_EVENT_TYPE


def test_casual_leaves_non_work_item_untouched() -> None:
    chat = _chat(0.8)
    recalled = (chat,)
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item is chat  # non-work is byte-identical even in CASUAL


def test_casual_preserves_order_and_length() -> None:
    recalled = (_chat(0.8), _work(1.0), _chat(0.7))
    result = filter_by_register(recalled, Register.CASUAL)
    assert len(result) == len(recalled)
    assert [item["content"] for item in result] == [
        item["content"] for item in recalled
    ]  # order-preserving, nothing excluded


def test_casual_work_score_ends_up_below_a_competing_chat() -> None:
    # A work memory that out-scored a chat in raw recall is muted below it in CASUAL,
    # so the chat wins the slot — yet the work memory still rides along (сквозной Боб).
    recalled = (_work(1.0), _chat(0.5))
    work_item, chat_item = filter_by_register(recalled, Register.CASUAL)
    assert float(str(work_item["score"])) < float(str(chat_item["score"]))
    assert work_item["content"] == "я попросил GUPPI…"


def test_empty_input_yields_empty_tuple() -> None:
    assert filter_by_register((), Register.CASUAL) == ()
    assert filter_by_register((), Register.DEV) == ()


def test_work_item_without_score_gets_a_concrete_attenuated_score() -> None:
    # Score-less work item still becomes rankable and low in CASUAL (baseline * weight).
    recalled = ({"content": "я доделал X", "category": WORK_EVENT_TYPE},)
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item["score"] == RECALL_WEIGHT_FULL * CASUAL_WORK_WEIGHT


def test_casual_attenuates_a_tag_only_work_item_through_the_filter() -> None:
    # A memory that is work ONLY by its provenance tag (non-work category) must still be
    # muted through the pipeline: proves the filter reads the ``tags`` key, not just category.
    recalled = (
        {
            "content": "я поднял лимит в раннере",
            "category": "episodic",
            "tags": ["dev", "actor:bob"],
            "score": 1.0,
        },
    )
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item["score"] == 1.0 * CASUAL_WORK_WEIGHT  # muted via the tag path, not category


def test_casual_scales_the_actual_score_not_a_baseline() -> None:
    # A non-unit score distinguishes reading the real ``score`` from a fixed baseline:
    # 4.0 * 0.15 = 0.6 (had the score been ignored/baselined to 1.0 it would read 0.15).
    recalled = (_work(4.0),)
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item["score"] == 4.0 * CASUAL_WORK_WEIGHT
    assert item["score"] != RECALL_WEIGHT_FULL * CASUAL_WORK_WEIGHT


def test_casual_treats_a_bool_score_as_absent_not_numeric() -> None:
    # A bool is never a real relevance score: it is baselined (→ 0.15), NOT coerced to a
    # float (a mis-coerced ``False`` would collapse to 0.0 and silently drop the item).
    recalled = ({"content": "я доделал X", "category": WORK_EVENT_TYPE, "score": False},)
    (item,) = filter_by_register(recalled, Register.CASUAL)
    assert item["score"] == RECALL_WEIGHT_FULL * CASUAL_WORK_WEIGHT
