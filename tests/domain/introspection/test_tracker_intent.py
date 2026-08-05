# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure tracker-intent planner (BOB-090.A).

:func:`plan_tracker_query` is the deterministic, I/O-free decision "what is this
person actually asking the tracker for?" — the ready queue, a listing (optionally
filtered by status), one task by id, or a SEARCH by epic key / word. It is the core
the live symptom broke on: «какие открыты?» produced no listing intent at all, and
«расскажи про BOB-087» produced a doomed ``bd show`` on prose.

Pure: no subprocess, no disk. This is a mutation target.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.tracker_intent import (
    TrackerPlan,
    find_bead_key,
    plan_tracker_query,
)

# --- the ready queue ----------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "\n"])
def test_empty_query_asks_for_the_ready_queue(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="ready")


@pytest.mark.parametrize("query", ["ready", "готовые задачи", "что готово"])
def test_ready_keywords_ask_for_the_ready_queue(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="ready")


# --- listings by status -------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["какие открыты?", "открытые задачи", "что открыто", "what is open", "open tasks"],
)
def test_open_question_lists_open_tasks(query: str) -> None:
    # 🔴 THE live symptom: «какие открыты?» -> «Пусто». There was no open keyword,
    # so the question fell through to a doomed ``bd show`` on prose.
    assert plan_tracker_query(query) == TrackerPlan(kind="list", argument="open")


@pytest.mark.parametrize(
    "query",
    ["закрытые", "недавние задачи", "recent", "история", "closed tasks"],
)
def test_closed_question_lists_closed_tasks(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="list", argument="closed")


@pytest.mark.parametrize(
    "query",
    ["в работе", "in progress", "in-progress", "покажи чем ты занят сегодня"],
)
def test_in_progress_question_lists_in_progress_tasks(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(
        kind="list", argument="in_progress"
    )


@pytest.mark.parametrize("query", ["все задачи", "all tasks", "весь список"])
def test_all_question_lists_unfiltered(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="list", argument=None)


@pytest.mark.parametrize(
    ("query", "status"),
    [
        # Every keyword of the map is pinned individually: a mutation run showed that
        # a multi-keyword phrase ("весь список") lets a DROPPED word survive, because
        # its neighbour still matches. One phrase per word, or the gate is fiction.
        ("history", "closed"),
        ("истории хочу", "closed"),
        ("недавние", "closed"),
        ("что recent", "closed"),
        ("closed", "closed"),
        ("актуальные задачи", "open"),
        ("in-progress", "in_progress"),
        ("чем занят", "in_progress"),
    ],
)
def test_every_status_keyword_is_pinned(query: str, status: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="list", argument=status)


@pytest.mark.parametrize("query", ["весь бэклог", "список задач", "list", "all"])
def test_every_unfiltered_listing_keyword_is_pinned(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(kind="list", argument=None)


def test_closed_wins_over_open_when_both_are_mentioned() -> None:
    # Deterministic precedence (first match wins), pinned so a reordering is visible.
    assert plan_tracker_query("закрытые и открытые") == TrackerPlan(
        kind="list", argument="closed"
    )


# --- one task by id -----------------------------------------------------------


@pytest.mark.parametrize("query", ["bob-9eh", "bob-alr.1", "BOB-087", "  bob-abk  "])
def test_bare_id_shows_that_task(query: str) -> None:
    assert plan_tracker_query(query) == TrackerPlan(
        kind="show", argument=query.strip()
    )


# --- search by epic key / word ------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected_key"),
    [
        ("расскажи про нашу задачу BOB-087", "BOB-087"),
        ("что там по bob-alr.1?", "bob-alr.1"),
        ("BOB-090 — как оно?", "BOB-090"),
        ("статус bob-abk, коротко", "bob-abk"),
    ],
)
def test_key_inside_a_phrase_becomes_a_search_for_that_key(
    query: str, expected_key: str
) -> None:
    # 🔴 bd matches a title SUBSTRING, so searching the whole phrase finds nothing —
    # the key must be cut out of the sentence.
    assert plan_tracker_query(query) == TrackerPlan(
        kind="search", argument=expected_key
    )


def test_key_in_a_phrase_wins_over_a_listing_keyword() -> None:
    # A question ABOUT one epic is not a request to list every closed task.
    assert plan_tracker_query("что закрыто по BOB-087") == TrackerPlan(
        kind="search", argument="BOB-087"
    )


@pytest.mark.parametrize(
    "query",
    ["совсем другая тема", "открывашка", "закрывашка"],
)
def test_keyword_matching_is_by_word_prefix_not_bare_substring(query: str) -> None:
    # 🔴 "все" hides inside "совсем", "открыт" inside "открывашка" — a bare substring
    # map turns an ordinary sentence into a listing request. Matching a WORD prefix
    # keeps inflection ("закрытые") working without the false positives.
    assert plan_tracker_query(query).kind == "search"


def test_inflected_keyword_still_matches_by_prefix() -> None:
    assert plan_tracker_query("что закрыто на прошлой неделе") == TrackerPlan(
        kind="list", argument="closed"
    )
    assert plan_tracker_query("по открытым задачам") == TrackerPlan(
        kind="list", argument="open"
    )


def test_free_text_without_key_or_keyword_becomes_a_search() -> None:
    assert plan_tracker_query("рефакторинг памяти") == TrackerPlan(
        kind="search", argument="рефакторинг памяти"
    )


def test_unusable_free_text_falls_back_to_the_plain_list() -> None:
    # Nothing safe survives sanitising -> never a search on an empty/flag term.
    assert plan_tracker_query("--status") == TrackerPlan(kind="list", argument=None)


def test_search_argument_is_always_sanitised() -> None:
    # 🔴 The BOB-087.D2 invariant end-to-end: a flag-shaped fragment in the question
    # can never come out as the search term.
    plan = plan_tracker_query("--limit 0 рефакторинг")
    assert plan == TrackerPlan(kind="search", argument="0 рефакторинг")


@pytest.mark.parametrize(
    "query",
    ["--status all", "-n 9999 --limit 0", "какие открыты?", "расскажи про BOB-087"],
)
def test_no_plan_argument_is_ever_flag_shaped(query: str) -> None:
    argument = plan_tracker_query(query).argument
    assert argument is None or not argument.startswith("-")


# --- find_bead_key ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("BOB-087", "BOB-087"),
        ("про BOB-087.", "BOB-087"),
        ("см. [BOB-090].A", "BOB-090"),
        ("bob-alr.10 готова", "bob-alr.10"),
        ("in features/bob-abk дела", "bob-abk"),
    ],
)
def test_find_bead_key_extracts_the_key(text: str, expected: str) -> None:
    assert find_bead_key(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "просто текст без ключа",
        "bobcat-1",  # not a bead prefix
        "abob-1",  # glued to a preceding word char
        "BOB",  # no number
        "BOB-",  # no number
    ],
)
def test_find_bead_key_returns_none_without_a_key(text: str) -> None:
    assert find_bead_key(text) is None
