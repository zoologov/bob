# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты worktree_branch — безопасная slug-ветка bob/<slug> (BOB-039 .1).

Чистая детерминированная функция: lowercase, только ascii [a-z0-9-], дефисы вместо
пробелов/спецсимволов, без path-инъекций (`..`, слэши, пробелы), ограниченная длина,
непустой fallback для не-ascii ввода.
"""

from __future__ import annotations

from bob.domain.coding.naming import worktree_branch

_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789-/")


def test_branch_has_bob_prefix() -> None:
    assert worktree_branch("Fix the parser").startswith("bob/")


def test_slugifies_spaces_and_case() -> None:
    assert worktree_branch("Fix The Parser") == "bob/fix-the-parser"


def test_no_path_injection_characters() -> None:
    branch = worktree_branch("../../etc/passwd  ; rm -rf")
    slug = branch[len("bob/") :]
    assert ".." not in slug
    assert "/" not in slug
    assert " " not in slug
    assert set(branch) <= _SAFE


def test_collapses_special_character_runs() -> None:
    assert worktree_branch("a@@@b###c") == "bob/a-b-c"


def test_strips_leading_and_trailing_hyphens() -> None:
    branch = worktree_branch("  !!hello!!  ")
    assert branch == "bob/hello"


def test_non_ascii_falls_back_to_non_empty_slug() -> None:
    branch = worktree_branch("починить парсер")
    slug = branch[len("bob/") :]
    assert slug  # непустой
    assert set(branch) <= _SAFE


def test_length_is_bounded() -> None:
    branch = worktree_branch("word " * 100)
    slug = branch[len("bob/") :]
    assert 0 < len(slug) <= 40
    assert not slug.endswith("-")


def test_empty_task_yields_fallback() -> None:
    assert worktree_branch("") == "bob/task"
    assert worktree_branch("   ") == "bob/task"
