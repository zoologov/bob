# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure code-history parsers (BOB-038 .1).

``parse_bead_refs`` lifts the ``[BOB-XXX]`` decision keys out of ``git log`` text
(de-duplicated, order-preserving) and ``feature_doc_dir`` maps a bead key to its
feature-doc directory. Both are pure, deterministic domain predicates — no I/O.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.code_history import (
    commits_mentioning,
    feature_doc_dir,
    parse_bead_refs,
)

# --- parse_bead_refs ----------------------------------------------------------


def test_parse_bead_refs_extracts_multiple_keys_in_order() -> None:
    text = (
        "29ceac1 [BOB-037] Схемы: авто-рендер (#44)\n"
        "a8a5231 [BOB-036] Фраза-тик (#43)\n"
        "20d4fc2 [BOB-035] Навык render_diagram (#41)\n"
    )
    assert parse_bead_refs(text) == ["BOB-037", "BOB-036", "BOB-035"]


def test_parse_bead_refs_dedupes_preserving_first_seen_order() -> None:
    text = (
        "aaa [BOB-017] feat: seam\n"
        "bbb [BOB-031] fix: grounding\n"
        "ccc [BOB-017] refactor: tidy\n"
    )
    assert parse_bead_refs(text) == ["BOB-017", "BOB-031"]


def test_parse_bead_refs_normalises_case_to_uppercase() -> None:
    text = "z [bob-034] read-scope\nz2 [BOB-034] follow-up\n"
    assert parse_bead_refs(text) == ["BOB-034"]


def test_parse_bead_refs_ignores_noise_and_non_bracketed_mentions() -> None:
    text = (
        "deadbee chore: bump deps, mentions BOB-999 without brackets\n"
        "f00 [ROADMAP] docs: sync\n"
        "beef [#42] not-a-bead\n"
    )
    assert parse_bead_refs(text) == []


def test_parse_bead_refs_returns_empty_on_no_match() -> None:
    assert parse_bead_refs("") == []
    assert parse_bead_refs("just some prose with no commit keys") == []


# --- feature_doc_dir ----------------------------------------------------------


def test_feature_doc_dir_maps_key_to_feature_docs_path() -> None:
    assert (
        feature_doc_dir("BOB-038")
        == ".claude/development/docs/features/BOB-038"
    )


def test_feature_doc_dir_normalises_case() -> None:
    assert (
        feature_doc_dir("bob-025")
        == ".claude/development/docs/features/BOB-025"
    )


def test_feature_doc_dir_strips_surrounding_whitespace() -> None:
    assert (
        feature_doc_dir("  BOB-017  ")
        == ".claude/development/docs/features/BOB-017"
    )


@pytest.mark.parametrize(
    "bad",
    ["", "garbage", "BOB-", "bob-4be.1", "BOB-12a", "DROP TABLE", "../etc"],
)
def test_feature_doc_dir_rejects_a_bad_key(bad: str) -> None:
    with pytest.raises(ValueError, match="bead key"):
        feature_doc_dir(bad)


# --- commits_mentioning -------------------------------------------------------


def test_commits_mentioning_returns_only_lines_bracketing_the_key() -> None:
    text = (
        "29ceac1 [BOB-037] Схемы: авто-рендер (#44)\n"
        "a8a5231 [BOB-036] Фраза-тик (#43)\n"
        "20d4fc2 [BOB-037] follow-up to render (#45)\n"
    )
    assert commits_mentioning("BOB-037", text) == [
        "29ceac1 [BOB-037] Схемы: авто-рендер (#44)",
        "20d4fc2 [BOB-037] follow-up to render (#45)",
    ]


def test_commits_mentioning_matches_key_case_insensitively() -> None:
    text = "aaa [bob-034] read-scope\nbbb [BOB-035] other\n"
    assert commits_mentioning("BOB-034", text) == ["aaa [bob-034] read-scope"]


def test_commits_mentioning_does_not_match_a_different_numbered_key() -> None:
    # ``[BOB-3]`` must not be matched when asked for ``BOB-37`` (and vice-versa).
    text = "aaa [BOB-3] tiny\nbbb [BOB-37] big\n"
    assert commits_mentioning("BOB-3", text) == ["aaa [BOB-3] tiny"]


def test_commits_mentioning_returns_empty_for_a_non_feature_key() -> None:
    text = "aaa [BOB-037] x\n"
    assert commits_mentioning("bob-4be.1", text) == []
    assert commits_mentioning("", text) == []


def test_commits_mentioning_returns_empty_on_no_match() -> None:
    assert commits_mentioning("BOB-099", "aaa [BOB-037] x\n") == []
