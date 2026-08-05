# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure tracker-search digest (BOB-090.A).

A search for an epic key legitimately matches DOZENS of tasks (``BOB-087`` matches 39
on the live tracker). Dumping 39 lines into a chat is the wall-of-text BOB-086 exists
to prevent, so :func:`digest_search_results` condenses a long listing into "the epic +
what is still alive + how many are closed", and leaves a SHORT listing untouched.

Pure: text in, text out. This is a mutation target.
"""

from __future__ import annotations

from bob.capabilities.introspection.tracker_digest import (
    MAX_DIGEST_ITEMS,
    digest_search_results,
)


def _entry(ident: str, kind: str, status: str, title: str = "задача") -> str:
    """One ``bd search`` result line, in the exact CLI shape."""
    return f"{ident} [P1] [{kind}] {status} @v.zoologov - {title}"


def _listing(entries: list[str], *, query: str = "BOB-087") -> str:
    header = f"Found {len(entries)} issues matching '{query}':"
    return "\n".join([header, *entries])


def _closed_swarm(count: int) -> list[str]:
    return [_entry(f"bob-abk.{i}", "task", "closed") for i in range(count)]


# --- a short listing is already readable: hands off ---------------------------


def test_short_listing_is_returned_unchanged() -> None:
    raw = _listing([_entry("bob-alr.1", "task", "in_progress")])
    assert digest_search_results(raw) == raw


def test_listing_at_the_cap_is_returned_unchanged() -> None:
    raw = _listing(_closed_swarm(MAX_DIGEST_ITEMS))
    assert digest_search_results(raw) == raw


def test_non_listing_output_is_returned_unchanged() -> None:
    raw = "No issues found matching 'BOB-999'"
    assert digest_search_results(raw) == raw


def test_empty_output_is_returned_unchanged() -> None:
    assert digest_search_results("") == ""


# --- a long listing is condensed ----------------------------------------------


def test_one_over_the_cap_is_condensed() -> None:
    raw = _listing(_closed_swarm(MAX_DIGEST_ITEMS + 1))
    assert digest_search_results(raw) != raw


def test_closed_epic_digest_shows_the_epic_and_the_counts() -> None:
    # 🔴 The live case: «расскажи про BOB-087» matches 39 tasks, all closed.
    epic = _entry("bob-abk", "epic", "closed", "BOB-087 человечный dev-Боб")
    raw = _listing([*_closed_swarm(38), epic])

    digest = digest_search_results(raw)

    assert "Найдено: 39" in digest
    assert "закрытых 39" in digest
    assert "bob-abk [P1] [epic] closed" in digest  # the epic itself survives
    assert "Скрыто: 38" in digest
    assert len(digest.splitlines()) == 3  # summary + epic + honest tail


def test_digest_surfaces_what_is_still_alive() -> None:
    alive = [
        _entry("bob-alr.1", "task", "in_progress", "A трекер отвечает"),
        _entry("bob-alr.2", "task", "open", "B адресация"),
    ]
    raw = _listing([*_closed_swarm(20), *alive])

    digest = digest_search_results(raw)

    assert "A трекер отвечает" in digest
    assert "B адресация" in digest
    assert "открытых 1" in digest
    assert "в работе 1" in digest
    assert "закрытых 20" in digest


def test_digest_never_shows_more_than_the_cap() -> None:
    alive = [_entry(f"bob-x.{i}", "task", "open") for i in range(30)]
    raw = _listing(alive)

    digest = digest_search_results(raw)
    shown = [line for line in digest.splitlines() if line.startswith("bob-x.")]

    assert len(shown) == MAX_DIGEST_ITEMS
    assert "Скрыто: 20" in digest


def test_digest_counts_every_entry_honestly() -> None:
    raw = _listing(
        [
            *_closed_swarm(12),
            _entry("bob-b", "task", "blocked"),
            _entry("bob-d", "task", "deferred"),
        ]
    )

    digest = digest_search_results(raw)

    assert "Найдено: 14" in digest
    assert "закрытых 12" in digest
    assert "прочих 2" in digest


def test_digest_summary_line_is_exact() -> None:
    # The whole line, verbatim: it pins the separator AND the running total across
    # buckets (with only one bucket filled, a broken accumulator looks correct).
    raw = _listing(
        [
            *_closed_swarm(20),
            _entry("bob-o1", "task", "open"),
            _entry("bob-o2", "task", "open"),
            _entry("bob-w1", "task", "in_progress"),
            _entry("bob-b1", "task", "blocked"),
        ]
    )

    assert digest_search_results(raw).splitlines()[0] == (
        "Найдено: 24 — открытых 2, в работе 1, закрытых 20, прочих 1."
    )


def test_digest_omits_a_bucket_that_is_empty() -> None:
    raw = _listing(_closed_swarm(MAX_DIGEST_ITEMS + 5))

    digest = digest_search_results(raw)

    assert "открытых" not in digest
    assert "в работе" not in digest
    assert "прочих" not in digest


def test_digest_keeps_the_epic_before_the_open_tasks() -> None:
    epic = _entry("bob-alr", "epic", "open", "эпик")
    children = [_entry(f"bob-alr.{i}", "task", "open", f"часть {i}") for i in range(15)]
    raw = _listing([*children, epic])

    lines = digest_search_results(raw).splitlines()
    epic_index = next(i for i, line in enumerate(lines) if "[epic]" in line)
    first_child = next(i for i, line in enumerate(lines) if "bob-alr.0 " in line)

    assert epic_index < first_child


def test_digest_surfaces_a_closed_feature_like_a_closed_epic() -> None:
    # A feature node is a container too — it answers "what was this about".
    feature = _entry("bob-l51", "feature", "closed", "единая публичная память")
    raw = _listing([*_closed_swarm(MAX_DIGEST_ITEMS + 1), feature])

    assert "единая публичная память" in digest_search_results(raw)


def test_digest_ignores_lines_that_are_not_result_entries() -> None:
    # A truncation marker / stray prose must not be counted as a task.
    raw = _listing(_closed_swarm(MAX_DIGEST_ITEMS + 1)) + "\n…[truncated]\n"

    digest = digest_search_results(raw)

    assert f"Найдено: {MAX_DIGEST_ITEMS + 1}" in digest
    assert "truncated" not in digest


def test_digest_drops_the_english_cli_header() -> None:
    raw = _listing(_closed_swarm(MAX_DIGEST_ITEMS + 1))
    assert "Found" not in digest_search_results(raw)
