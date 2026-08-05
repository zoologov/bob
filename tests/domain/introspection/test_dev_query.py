# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure ``dev_query`` validation core (BOB-081.1).

The deterministic, I/O-free predicates that shape every dynamic value passed to a
subprocess (commit count, bead id, tracker status). This is the mutation target:
``clamp_commit_count`` bounds history size, ``validate_bead_id`` is the injection
guard on ids forwarded to ``bd``/``git``, and ``normalize_status`` maps a free-text
status to the tracker enum. No subprocess, no disk.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.dev_query import (
    MAX_SEARCH_TERM_CHARS,
    clamp_commit_count,
    is_bead_id,
    normalize_status,
    sanitize_search_term,
    validate_bead_id,
)

# --- clamp_commit_count -------------------------------------------------------


def test_clamp_commit_count_none_is_default() -> None:
    assert clamp_commit_count(None) == 10


def test_clamp_commit_count_zero_clamps_to_min() -> None:
    assert clamp_commit_count(0) == 1


def test_clamp_commit_count_negative_clamps_to_min() -> None:
    assert clamp_commit_count(-5) == 1


def test_clamp_commit_count_min_boundary_kept() -> None:
    assert clamp_commit_count(1) == 1


def test_clamp_commit_count_in_range_kept() -> None:
    assert clamp_commit_count(10) == 10
    assert clamp_commit_count(37) == 37


def test_clamp_commit_count_max_boundary_kept() -> None:
    assert clamp_commit_count(50) == 50


def test_clamp_commit_count_above_max_clamps_to_max() -> None:
    assert clamp_commit_count(51) == 50
    assert clamp_commit_count(10_000) == 50


# --- validate_bead_id ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "BOB-076",
        "bob-0gj",
        "bob-0gj.1",
        "BOB-081.2",
        "bob-4be.10",
        "  BOB-076  ",  # trimmed
        "bob-9eh",
    ],
)
def test_validate_bead_id_accepts_bead_keys(raw: str) -> None:
    assert validate_bead_id(raw) == raw.strip()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "--flag",
        "-x",
        "a;b",
        "BOB-076; rm -rf /",
        "../x",
        "x y",
        "BOB-",  # no digits
        "bob-",  # empty tail
        "BOB-076.foo",  # non-numeric suffix
        "$(whoami)",
        "bob 076",
        "BOB-076\n",  # embedded newline (strip leaves BOB-076? no: strip removes it)
    ],
)
def test_validate_bead_id_rejects_injections(raw: str) -> None:
    # "BOB-076\n" trims to "BOB-076" and is actually valid — assert the others raise.
    if raw.strip() == "BOB-076":
        assert validate_bead_id(raw) == "BOB-076"
        return
    with pytest.raises(ValueError, match="bead"):
        validate_bead_id(raw)


# --- is_bead_id ---------------------------------------------------------------


@pytest.mark.parametrize("raw", ["BOB-076", "bob-0gj", "bob-0gj.1", "  BOB-076  "])
def test_is_bead_id_accepts_bead_keys(raw: str) -> None:
    assert is_bead_id(raw) is True


@pytest.mark.parametrize("raw", ["", "какие открыты", "--flag", "bob-", "BOB-076.foo"])
def test_is_bead_id_rejects_non_keys(raw: str) -> None:
    assert is_bead_id(raw) is False


# --- normalize_status ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["open", "in_progress", "blocked", "deferred", "closed"],
)
def test_normalize_status_allowlist_passthrough(raw: str) -> None:
    assert normalize_status(raw) == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("в работе", "in_progress"),
        ("закрытые", "closed"),
        ("закрыто", "closed"),
        ("открытые", "open"),
        ("OPEN", "open"),  # case-insensitive
        ("  closed  ", "closed"),  # trimmed
    ],
)
def test_normalize_status_synonyms(raw: str, expected: str) -> None:
    assert normalize_status(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "unknown", "done", "wip", "--status", "closed;drop"],
)
def test_normalize_status_unknown_is_none(raw: str | None) -> None:
    assert normalize_status(raw) is None


# --- 🔴 injection-vector gap-fill (BOB-081.3) ---------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "BOB-1 | cat /etc/passwd",  # pipe
        "BOB-1 && whoami",  # command chain
        "`id`",  # backtick substitution
        "/etc/passwd",  # absolute path
        "../../etc/passwd",  # deeper traversal
        "-n 9999",  # a bare flag+value
        "BOB-1\t",  # embedded tab is stripped, tail invalid? -> BOB-1 is valid
        "BOB_1",  # underscore, not a hyphen key
        "bob-",  # empty node tail
    ],
)
def test_validate_bead_id_rejects_more_injection_vectors(raw: str) -> None:
    # "BOB-1\t" trims to a valid "BOB-1" — assert the genuinely hostile ones raise.
    if raw.strip() == "BOB-1":
        assert validate_bead_id(raw) == "BOB-1"
        return
    with pytest.raises(ValueError, match="bead"):
        validate_bead_id(raw)


# --- mutation-hardening on the exact bounds/branches --------------------------


def test_clamp_commit_count_just_above_min_is_kept() -> None:
    # Kills an off-by-one on the min bound (2 must survive as 2, not clamp to 1).
    assert clamp_commit_count(2) == 2


def test_clamp_commit_count_just_below_max_is_kept() -> None:
    # Kills an off-by-one on the max bound (49 must survive as 49, not clamp to 50).
    assert clamp_commit_count(49) == 49


def test_normalize_status_synonym_is_not_an_enum_passthrough() -> None:
    # The synonym branch (not the enum branch) maps "закрытые" — a mutant that returned
    # the raw token instead of the mapped enum would give "закрытые", not "closed".
    assert normalize_status("закрытые") == "closed"
    assert normalize_status("закрытые") != "закрытые"


# --- sanitize_search_term (BOB-090.A) -----------------------------------------
# 🔴 The free-text search term is the FIRST user-authored string to reach argv, so it
# is the BOB-087.D2 lesson in miniature: a value that starts with a dash is read by the
# option parser as a FLAG. These tests pin the guard.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BOB-087", "BOB-087"),
        ("bob-alr.1", "bob-alr.1"),
        ("память", "память"),
        ("  память  ", "память"),  # trimmed
        ("трекер   отвечает", "трекер отвечает"),  # inner runs collapse
        ("что там по памяти?", "что там по памяти?"),  # punctuation is harmless (no shell)
    ],
)
def test_sanitize_search_term_keeps_plain_text(raw: str, expected: str) -> None:
    assert sanitize_search_term(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["--status", "-n", "-", "--", "--status --limit", "---"],
)
def test_sanitize_search_term_drops_pure_flag_input(raw: str) -> None:
    # Every token is flag-shaped -> nothing safe is left -> None (no search is run).
    assert sanitize_search_term(raw) is None


def test_sanitize_search_term_drops_flag_token_but_keeps_words() -> None:
    # A flag hidden inside prose is dropped; the harmless words survive as the query.
    assert sanitize_search_term("память --desc-contains пароль") == "память пароль"
    assert sanitize_search_term("-n 50") == "50"
    assert sanitize_search_term("--status all") == "all"


def test_sanitize_search_term_never_returns_a_flag_shaped_value() -> None:
    # The invariant the adapter relies on: whatever comes back can never be read as a
    # flag by the option parser.
    for raw in ("--status all", "-x", "-- BOB-087", "  --limit 0 память"):
        term = sanitize_search_term(raw)
        assert term is None or not term.startswith("-")


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", "\x00"])
def test_sanitize_search_term_empty_is_none(raw: str) -> None:
    assert sanitize_search_term(raw) is None


def test_sanitize_search_term_strips_control_chars_without_gluing_words() -> None:
    # A NUL terminates a C string mid-argv; a newline splits a line. Both become a
    # separator, so neighbouring words stay separate words (never "abc" from "a\x00bc").
    assert sanitize_search_term("a\x00bc") == "a bc"
    assert sanitize_search_term("BOB-087\nBOB-090") == "BOB-087 BOB-090"
    assert sanitize_search_term("a\tb") == "a b"


def test_sanitize_search_term_is_length_bounded() -> None:
    long_raw = "x" * (MAX_SEARCH_TERM_CHARS * 3)
    term = sanitize_search_term(long_raw)
    assert term is not None
    assert len(term) == MAX_SEARCH_TERM_CHARS


def test_sanitize_search_term_is_idempotent() -> None:
    # The adapter re-validates argv by re-running the sanitiser, so a sanitised value
    # MUST sanitise to itself — otherwise a legitimate search would be refused.
    for raw in ("BOB-087", "память секрет", "50", "x" * 500, "  два слова  "):
        once = sanitize_search_term(raw)
        assert once is not None
        assert sanitize_search_term(once) == once
