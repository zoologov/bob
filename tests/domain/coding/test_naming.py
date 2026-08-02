# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты worktree_branch — безопасная slug-ветка bob/<slug> (BOB-039 .1).

Чистая детерминированная функция: lowercase, только ascii [a-z0-9-], дефисы вместо
пробелов/спецсимволов, без path-инъекций (`..`, слэши, пробелы), ограниченная длина,
непустой fallback для не-ascii ввода.
"""

from __future__ import annotations

from bob.coding.adapters._branch import is_safe_branch
from bob.coding.naming import workspace_branch, worktree_branch

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


def test_leading_junk_does_not_eat_into_the_length_budget() -> None:
    # Ведущий мусор срезается ДО обрезки по длине, иначе он съедал бы часть бюджета в
    # 40 символов и slug терял бы значащий хвост (а после второй обрезки становился бы
    # короче на длину мусора).
    branch = worktree_branch("### " + "a" * 45)
    assert branch == "bob/" + "a" * 40


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


# --- workspace_branch: a long-lived NAMED workspace branch (BOB-087.D1) ---


def test_workspace_branch_is_epic_namespaced() -> None:
    assert workspace_branch("BOB-087") == "bob/epic-bob-087"


def test_workspace_branch_is_a_safe_bob_slug_shape() -> None:
    # It must pass the SAME infrastructure safety gate as an ephemeral session branch,
    # so it can never smuggle a path segment / flag into a git argv slot.
    assert is_safe_branch(workspace_branch("Some Epic Key"))


def test_workspace_branch_has_no_path_injection() -> None:
    branch = workspace_branch("../../etc/passwd  ; rm -rf")
    assert set(branch) <= _SAFE
    assert ".." not in branch


def test_workspace_branch_is_distinct_from_an_ephemeral_session_branch() -> None:
    # The persistent workspace lives in its OWN ``epic-`` namespace so it never
    # collides with a per-task ephemeral ``bob/<slug>`` session branch.
    key = "fix parser"
    assert workspace_branch(key) != worktree_branch(key)


def test_workspace_branch_non_ascii_falls_back_to_non_empty_slug() -> None:
    branch = workspace_branch("эпик")
    assert is_safe_branch(branch)
    assert set(branch) <= _SAFE
