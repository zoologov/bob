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
    clamp_commit_count,
    normalize_status,
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
