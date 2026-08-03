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


def test_cyrillic_is_transliterated_not_thrown_away() -> None:
    # 🔴 BOB-087.D5b (M2): язык проекта — русский. Кириллица ОТБРАСЫВАЛАСЬ, поэтому любое
    # русское имя схлопывалось в один и тот же fallback-slug.
    branch = worktree_branch("починить парсер")

    assert branch == "bob/pochinit-parser"
    assert set(branch) <= _SAFE


def test_transliteration_covers_the_awkward_letters() -> None:
    assert worktree_branch("ёжик щи юла яма ъ ь") == "bob/ezhik-schi-yula-yama"


def test_mixed_latin_and_cyrillic_keeps_both() -> None:
    assert worktree_branch("Fix парсер 2") == "bob/fix-parser-2"


def test_a_script_we_do_not_transliterate_degrades_instead_of_crashing() -> None:
    # Транслитерация покрывает кириллицу; всё ОСТАЛЬНОЕ не-ascii (CJK, эмодзи) обязано
    # ТИХО отбрасываться. Это про устойчивость: имя ветки строится из свободного текста
    # owner'а, и незнакомый символ не смеет уронить старт сессии исключением.
    branch = worktree_branch("修复 парсер 🚀 now")

    assert branch == "bob/parser-now"
    assert set(branch) <= _SAFE


def test_a_name_made_only_of_unsupported_script_falls_back() -> None:
    branch = worktree_branch("修复")

    assert branch == "bob/task"  # непустой fallback, а не пустая (невалидная) ветка


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


def test_workspace_branch_transliterates_a_cyrillic_name() -> None:
    branch = workspace_branch("эпик")

    assert branch == "bob/epic-epik"
    assert is_safe_branch(branch)
    assert set(branch) <= _SAFE


def test_distinct_cyrillic_workspace_names_do_not_collide() -> None:
    # 🔴 THE M2 failure: «эпик», «проект» и «Боб» схлопывались в ОДИН bob/epic-task, так
    # что «/resume проект» поднимал бы чужую накопленную сессию, называя её «проект».
    names = ("эпик", "проект", "Боб", "релиз")
    branches = [workspace_branch(name) for name in names]

    assert len(set(branches)) == len(names), branches
    assert all(is_safe_branch(branch) for branch in branches)


def test_workspace_branch_of_a_russian_issue_key_is_readable() -> None:
    assert workspace_branch("БОБ-087") == "bob/epic-bob-087"
