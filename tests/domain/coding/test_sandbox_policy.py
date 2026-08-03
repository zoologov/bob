# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты sandbox_policy — политика owner-ослаблений изоляции claude (BOB-087.D2).

Чистое доменное ядро (mutation-цель): какие ``--permission-mode`` вообще разрешено
передать процессу (база ``{plan, acceptEdits}``; ``bypassPermissions`` — ТОЛЬКО под
явным owner-флагом) и во что превращается список доп-директорий ``--add-dir``
(санитайз против argv-инъекции, дедуп, кэп). Оба ослабления по умолчанию выключены,
поэтому дефолтный путь обязан быть байт-в-байт прежним.
"""

from __future__ import annotations

from bob.coding.sandbox_policy import (
    BASE_PERMISSION_MODES,
    BYPASS_PERMISSION_MODE,
    MAX_EXTRA_DIRS,
    allowed_modes,
    extra_dir_argv,
    is_allowed_mode,
)

# --------------------------------------------------------------------------- #
# allowed_modes / is_allowed_mode — allowlist режимов
# --------------------------------------------------------------------------- #


def test_base_allowlist_is_exactly_plan_and_accept_edits() -> None:
    assert allowed_modes(allow_bypass=False) == frozenset({"plan", "acceptEdits"})
    assert set(BASE_PERMISSION_MODES) == {"plan", "acceptEdits"}


def test_bypass_is_absent_without_the_owner_flag() -> None:
    # OFF-путь (дефолт): «no bypassPermissions ever» ровно как до D2.
    assert BYPASS_PERMISSION_MODE not in allowed_modes(allow_bypass=False)
    assert is_allowed_mode(BYPASS_PERMISSION_MODE, allow_bypass=False) is False


def test_bypass_appears_only_under_the_owner_flag() -> None:
    assert BYPASS_PERMISSION_MODE in allowed_modes(allow_bypass=True)
    assert is_allowed_mode(BYPASS_PERMISSION_MODE, allow_bypass=True) is True


def test_the_flag_adds_bypass_and_nothing_else() -> None:
    # Флаг РАСШИРЯЕТ базу ровно на один режим — не открывает allowlist целиком.
    assert allowed_modes(allow_bypass=True) == BASE_PERMISSION_MODES | {BYPASS_PERMISSION_MODE}


def test_base_modes_stay_allowed_under_the_flag() -> None:
    assert is_allowed_mode("plan", allow_bypass=True) is True
    assert is_allowed_mode("acceptEdits", allow_bypass=True) is True


def test_base_modes_are_allowed_without_the_flag() -> None:
    assert is_allowed_mode("plan", allow_bypass=False) is True
    assert is_allowed_mode("acceptEdits", allow_bypass=False) is True


def test_an_unknown_mode_is_refused_even_under_the_flag() -> None:
    # Флаг — это ОДИН дополнительный режим, а не «пропускать что угодно»:
    # мусор/инъекция/регистр/пустая строка отвергаются в обоих состояниях.
    for mode in ["", "PLAN", "plan; rm -rf /", "--dangerously-skip-permissions", "yolo"]:
        assert is_allowed_mode(mode, allow_bypass=False) is False
        assert is_allowed_mode(mode, allow_bypass=True) is False


def test_allowed_modes_result_is_immutable() -> None:
    # frozenset: вызывающий не может «дописать» себе режим в общий allowlist.
    assert isinstance(allowed_modes(allow_bypass=False), frozenset)


# --------------------------------------------------------------------------- #
# extra_dir_argv — санитайз доп-директорий в argv-фрагмент
# --------------------------------------------------------------------------- #


def test_no_extra_dirs_yields_an_empty_fragment() -> None:
    # OFF-путь (дефолт): ничего не приписывается — argv байт-в-байт прежний.
    assert extra_dir_argv(()) == []
    assert extra_dir_argv([]) == []


def test_one_dir_becomes_an_add_dir_pair() -> None:
    assert extra_dir_argv(["/srv/docs"]) == ["--add-dir", "/srv/docs"]


def test_each_dir_gets_its_own_add_dir_flag_in_order() -> None:
    assert extra_dir_argv(["/a", "/b"]) == ["--add-dir", "/a", "--add-dir", "/b"]


def test_blank_and_whitespace_only_entries_are_dropped() -> None:
    assert extra_dir_argv(["", "   ", "\t", "/a"]) == ["--add-dir", "/a"]


def test_surrounding_whitespace_is_stripped() -> None:
    assert extra_dir_argv(["  /a  "]) == ["--add-dir", "/a"]


def test_an_entry_that_looks_like_a_flag_is_dropped() -> None:
    # 🔴 argv-инъекция: строка, начинающаяся с '-', в argv-слоте стала бы ФЛАГОМ
    # claude (напр. --dangerously-skip-permissions), а не директорией.
    assert extra_dir_argv(["--dangerously-skip-permissions", "/a"]) == [
        "--add-dir",
        "/a",
    ]
    assert extra_dir_argv(["-p"]) == []
    # Тот же запрет и после strip: ведущие пробелы не «прячут» дефис.
    assert extra_dir_argv(["   --resume"]) == []


def test_an_entry_with_a_nul_byte_is_dropped() -> None:
    # NUL невыразим в argv (execve оборвал бы аргумент) — отбрасываем до спавна.
    assert extra_dir_argv(["/a\x00/b", "/ok"]) == ["--add-dir", "/ok"]


def test_duplicates_are_dropped_keeping_the_first_position() -> None:
    assert extra_dir_argv(["/a", "/b", "/a", " /b "]) == [
        "--add-dir",
        "/a",
        "--add-dir",
        "/b",
    ]


def test_the_number_of_dirs_is_capped() -> None:
    dirs = [f"/d{i}" for i in range(MAX_EXTRA_DIRS + 5)]

    fragment = extra_dir_argv(dirs)

    # Кэп: ослабление изоляции остаётся ОГРАНИЧЕННЫМ — берутся первые MAX_EXTRA_DIRS.
    assert fragment.count("--add-dir") == MAX_EXTRA_DIRS
    assert fragment[:2] == ["--add-dir", "/d0"]
    assert f"/d{MAX_EXTRA_DIRS}" not in fragment


def test_the_cap_counts_only_kept_dirs() -> None:
    # Мусор не «съедает» лимит: отброшенные записи не занимают место под кэпом.
    dirs = ["", "-x", *[f"/d{i}" for i in range(MAX_EXTRA_DIRS)]]

    assert extra_dir_argv(dirs).count("--add-dir") == MAX_EXTRA_DIRS


def test_the_cap_is_overridable_per_call() -> None:
    assert extra_dir_argv(["/a", "/b", "/c"], max_dirs=2) == [
        "--add-dir",
        "/a",
        "--add-dir",
        "/b",
    ]


def test_a_non_positive_cap_yields_nothing() -> None:
    assert extra_dir_argv(["/a"], max_dirs=0) == []


def test_the_result_is_deterministic_and_a_fresh_list() -> None:
    dirs = ["/a", "/b"]

    first = extra_dir_argv(dirs)
    second = extra_dir_argv(dirs)

    assert first == second
    # Отдельный список на вызов — мутация результата не отравляет следующий вызов.
    assert first is not second
